package com.authorityclosers.salesxray;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.CallLog;
import android.telephony.PhoneStateListener;
import android.telephony.TelephonyCallback;
import android.telephony.TelephonyManager;
import androidx.annotation.RequiresApi;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Places a call for a lead and follows it. When the phone hangs up it reads the
 * phone's own call history (connected or not, and for how long) and looks for
 * the recording the phone's dialer saved. The page hears twice: when the call
 * ends, and again when the recording search is done ("final").
 * Nothing is uploaded here; the page asks the person first.
 */
final class CallTracker {

    interface Listener {
        void onCall(JSONObject call);
    }

    private static final String PREFS = "sx_calls";
    private static final String LAST = "last";
    private static final long LOG_WAIT_MS = 8_000;
    private static final long RECORDING_WAIT_MS = 30_000;
    private static final long POLL_MS = 1_500;
    /** A call that rang this long and never connected was most likely not answered. */
    private static final long RANG_OUT_MS = 20_000;
    /** A call older than this is no longer offered to the page. */
    private static final long KEEP_MS = 6L * 60 * 60 * 1000;

    private final AppCompatActivity activity;
    private final Listener listener;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private TelephonyManager telephony;
    private Object watcher;
    private boolean inCall;
    private boolean finishing;

    CallTracker(AppCompatActivity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
    }

    /** Calling, call history and the phone's recordings. */
    static String[] wanted() {
        List<String> list = new ArrayList<>();
        list.add(Manifest.permission.CALL_PHONE);
        list.add(Manifest.permission.READ_PHONE_STATE);
        list.add(Manifest.permission.READ_CALL_LOG);
        list.add(Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_AUDIO : Manifest.permission.READ_EXTERNAL_STORAGE);
        return list.toArray(new String[0]);
    }

    static String[] missing(Context context) {
        List<String> list = new ArrayList<>();
        for (String permission : wanted()) if (!granted(context, permission)) list.add(permission);
        return list.toArray(new String[0]);
    }

    static boolean hasCallAccess(Context context) {
        return (
            granted(context, Manifest.permission.CALL_PHONE) &&
            granted(context, Manifest.permission.READ_PHONE_STATE) &&
            granted(context, Manifest.permission.READ_CALL_LOG)
        );
    }

    private static boolean granted(Context context, String permission) {
        return ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED;
    }

    /** Starts the call: straight to the call when the phone allows it, otherwise the dialer with the number in. */
    JSONObject call(String leadId, String number, String name) {
        JSONObject call = new JSONObject();
        put(call, "leadId", leadId);
        put(call, "number", number);
        put(call, "name", name);
        put(call, "startedMs", System.currentTimeMillis());
        put(call, "endedMs", JSONObject.NULL);
        put(call, "final", false);
        synchronized (this) {
            save(call);
            finishing = false;
            inCall = false;
        }
        boolean direct = granted(activity, Manifest.permission.CALL_PHONE);
        Uri uri = Uri.fromParts("tel", number, null);
        try {
            activity.startActivity(new Intent(direct ? Intent.ACTION_CALL : Intent.ACTION_DIAL, uri));
        } catch (RuntimeException error) {
            direct = false;
            activity.startActivity(new Intent(Intent.ACTION_DIAL, uri));
        }
        watch();
        JSONObject started = new JSONObject();
        put(started, "started", true);
        put(started, "mode", direct ? "direct" : "dialer");
        return started;
    }

    /** The lead's last call, once it has ended; null while it is still on or when there is none. */
    JSONObject last(String leadId) {
        JSONObject call = load();
        if (call == null || !leadId.equals(call.optString("leadId"))) return null;
        if (System.currentTimeMillis() - call.optLong("startedMs") > KEEP_MS) {
            clear();
            return null;
        }
        if (call.isNull("endedMs")) {
            onResume();
            return null;
        }
        return call;
    }

    void forget(String leadId) {
        JSONObject call = load();
        if (call != null && leadId.equals(call.optString("leadId"))) clear();
    }

    /** Back in the app: a call that ended while the app was away is finished here. */
    void onResume() {
        JSONObject call = load();
        if (call == null || !call.isNull("endedMs")) return;
        if (System.currentTimeMillis() - call.optLong("startedMs") < 3_000) return;
        if (phoneBusy()) return;
        finish();
    }

    void onState(int state) {
        if (state == TelephonyManager.CALL_STATE_OFFHOOK) inCall = true;
        else if (state == TelephonyManager.CALL_STATE_IDLE && inCall) finish();
    }

    private synchronized void finish() {
        JSONObject call = load();
        if (call == null || finishing || !call.isNull("endedMs")) return;
        finishing = true;
        unwatch();
        put(call, "endedMs", System.currentTimeMillis());
        save(call);
        io.execute(() -> settle(call));
    }

    private void settle(JSONObject call) {
        readHistory(call);
        if (!keep(call)) return;
        listener.onCall(copy(call));
        bringBack();
        JSONObject recording = findRecording(call);
        put(call, "recording", recording == null ? JSONObject.NULL : recording);
        put(call, "final", true);
        if (!keep(call)) return;
        synchronized (this) {
            finishing = false;
        }
        listener.onCall(copy(call));
    }

    /** Saves the call unless the page has already forgotten it or a newer call started. */
    private synchronized boolean keep(JSONObject call) {
        JSONObject stored = load();
        if (stored == null || stored.optLong("startedMs") != call.optLong("startedMs")) return false;
        save(call);
        return true;
    }

    private void readHistory(JSONObject call) {
        long started = call.optLong("startedMs");
        long ended = call.optLong("endedMs");
        String digits = digits(call.optString("number"));
        if (granted(activity, Manifest.permission.READ_CALL_LOG)) {
            long deadline = System.currentTimeMillis() + LOG_WAIT_MS;
            do {
                Long seconds = loggedSeconds(started, digits);
                if (seconds != null) {
                    boolean talked = seconds > 0;
                    put(call, "durationSeconds", seconds);
                    put(call, "connected", talked);
                    put(call, "result", talked ? "answered" : ended - started >= RANG_OUT_MS ? "no_answer" : "unknown");
                    return;
                }
                sleep(POLL_MS);
            } while (System.currentTimeMillis() < deadline);
        }
        put(call, "durationSeconds", JSONObject.NULL);
        put(call, "connected", JSONObject.NULL);
        put(call, "result", "unknown");
    }

    /** Talk time of the outgoing call to this number placed since the call started, from the phone's history. */
    private Long loggedSeconds(long started, String digits) {
        String[] columns = { CallLog.Calls.NUMBER, CallLog.Calls.DURATION, CallLog.Calls.TYPE };
        try (
            Cursor cursor = activity
                .getContentResolver()
                .query(
                    CallLog.Calls.CONTENT_URI,
                    columns,
                    CallLog.Calls.DATE + " >= ?",
                    new String[] { String.valueOf(started - 10_000) },
                    CallLog.Calls.DATE + " DESC"
                )
        ) {
            if (cursor == null) return null;
            while (cursor.moveToNext()) {
                if (cursor.getInt(2) != CallLog.Calls.OUTGOING_TYPE) continue;
                if (!sameNumber(digits, digits(cursor.getString(0)))) continue;
                return cursor.getLong(1);
            }
        } catch (RuntimeException ignored) {
            // History unavailable: the person answers by hand.
        }
        return null;
    }

    private JSONObject findRecording(JSONObject call) {
        if (!RecordingScanner.hasAudioAccess(activity) && !RecordingScanner.hasAllFilesAccess()) return null;
        // No conversation, nothing worth analysing.
        if (Boolean.FALSE.equals(call.opt("connected"))) return null;
        long since = call.optLong("startedMs") - 5_000;
        long deadline = System.currentTimeMillis() + RECORDING_WAIT_MS;
        do {
            JSONObject found = RecordingScanner.newestSince(activity, since, call.optString("number"), call.optString("name"));
            if (found != null) return found;
            sleep(POLL_MS * 2);
        } while (System.currentTimeMillis() < deadline);
        return null;
    }

    /** Most phones return to the app after the call; this covers the ones that don't. */
    private void bringBack() {
        main.post(() -> {
            if (activity.hasWindowFocus() || activity.isFinishing()) return;
            try {
                Intent intent = new Intent(activity, MainActivity.class);
                intent.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                activity.startActivity(intent);
            } catch (RuntimeException ignored) {
                // Android may not let an app come forward by itself; the page asks when it is opened.
            }
        });
    }

    private void watch() {
        if (watcher != null || !granted(activity, Manifest.permission.READ_PHONE_STATE)) return;
        telephony = (TelephonyManager) activity.getSystemService(Context.TELEPHONY_SERVICE);
        if (telephony == null) return;
        try {
            if (Build.VERSION.SDK_INT >= 31) {
                Watcher31 callback = new Watcher31(this);
                telephony.registerTelephonyCallback(ContextCompat.getMainExecutor(activity), callback);
                watcher = callback;
            } else {
                OldWatcher callback = new OldWatcher(this);
                telephony.listen(callback, PhoneStateListener.LISTEN_CALL_STATE);
                watcher = callback;
            }
        } catch (RuntimeException error) {
            // Without call state the call is finished when the person comes back.
            watcher = null;
        }
    }

    @SuppressWarnings("deprecation")
    private void unwatch() {
        Object current = watcher;
        watcher = null;
        if (telephony == null || current == null) return;
        try {
            if (Build.VERSION.SDK_INT >= 31 && current instanceof TelephonyCallback) {
                telephony.unregisterTelephonyCallback((TelephonyCallback) current);
            } else if (current instanceof PhoneStateListener) {
                telephony.listen((PhoneStateListener) current, PhoneStateListener.LISTEN_NONE);
            }
        } catch (RuntimeException ignored) {
            // Already gone.
        }
    }

    @SuppressWarnings("deprecation")
    private boolean phoneBusy() {
        if (!granted(activity, Manifest.permission.READ_PHONE_STATE)) return false;
        try {
            TelephonyManager manager = (TelephonyManager) activity.getSystemService(Context.TELEPHONY_SERVICE);
            return manager != null && manager.getCallState() != TelephonyManager.CALL_STATE_IDLE;
        } catch (RuntimeException error) {
            return false;
        }
    }

    @RequiresApi(31)
    private static final class Watcher31 extends TelephonyCallback implements TelephonyCallback.CallStateListener {

        private final CallTracker tracker;

        Watcher31(CallTracker tracker) {
            this.tracker = tracker;
        }

        @Override
        public void onCallStateChanged(int state) {
            tracker.onState(state);
        }
    }

    @SuppressWarnings("deprecation")
    private static final class OldWatcher extends PhoneStateListener {

        private final CallTracker tracker;

        OldWatcher(CallTracker tracker) {
            this.tracker = tracker;
        }

        @Override
        public void onCallStateChanged(int state, String phoneNumber) {
            tracker.onState(state);
        }
    }

    static String digits(String raw) {
        return raw == null ? "" : raw.replaceAll("\\D", "");
    }

    /** The same number when the last ten digits match (so +91 and 0 prefixes don't matter). */
    static boolean sameNumber(String a, String b) {
        if (a.isEmpty() || b.isEmpty()) return false;
        int n = Math.min(10, Math.min(a.length(), b.length()));
        return a.substring(a.length() - n).equals(b.substring(b.length() - n));
    }

    private SharedPreferences prefs() {
        return activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private synchronized JSONObject load() {
        String raw = prefs().getString(LAST, null);
        if (raw == null) return null;
        try {
            return new JSONObject(raw);
        } catch (JSONException error) {
            return null;
        }
    }

    private synchronized void save(JSONObject call) {
        prefs().edit().putString(LAST, call.toString()).apply();
    }

    private synchronized void clear() {
        prefs().edit().remove(LAST).apply();
    }

    private static JSONObject copy(JSONObject call) {
        try {
            return new JSONObject(call.toString());
        } catch (JSONException error) {
            return new JSONObject();
        }
    }

    private static void put(JSONObject json, String key, Object value) {
        try {
            json.put(key, value);
        } catch (JSONException ignored) {
            // Keys and values here are always valid.
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        }
    }
}
