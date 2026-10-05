package com.authorityclosers.salesxray;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Base64;
import android.webkit.WebView;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The page talks to the phone through one origin-restricted message channel
 * ("SXPhone"). Only Sales Xray's own sites can call it, it works under the
 * site's content security policy, and it only lists and reads call recordings.
 */
final class PhoneBridge {

    static final Set<String> HOSTS = new HashSet<>(
        Arrays.asList(
            "salesxray.authorityclosers.com",
            "salesxray-staging.authorityclosers.com",
            "salesxray-dev.authorityclosers.com"
        )
    );

    private static final int REQUEST_AUDIO = 7101;
    private static final int REQUEST_NOTIFY = 7102;
    private static final int CHUNK = 512 * 1024;

    private final AppCompatActivity activity;
    private final WebView webView;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private String script;
    private String launchSource;
    private JavaScriptReplyProxy pendingReply;
    private String pendingId;

    PhoneBridge(AppCompatActivity activity, WebView webView) {
        this.activity = activity;
        this.webView = webView;
    }

    void attach() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return;
        Set<String> origins = new HashSet<>();
        for (String host : HOSTS) origins.add("https://" + host);
        WebViewCompat.addWebMessageListener(webView, "SXPhone", origins, (view, message, origin, isMainFrame, reply) -> {
            if (isMainFrame && message.getData() != null) handle(message.getData(), reply);
        });
    }

    /** Adds the "Calls on this phone" panel to Sales Xray pages only. */
    void inject(WebView view, String url) {
        Uri uri = Uri.parse(url);
        if (!"https".equals(uri.getScheme()) || !HOSTS.contains(uri.getHost())) return;
        if (script == null) script = asset("sx-phone.js");
        if (script != null) view.evaluateJavascript(script, null);
    }

    void takeLaunch(Intent intent) {
        if (intent == null) return;
        String source = intent.getStringExtra(RecordingWatchWorker.EXTRA_SOURCE);
        if (source != null) launchSource = source;
        intent.removeExtra(RecordingWatchWorker.EXTRA_SOURCE);
    }

    void signal(String event) {
        main.post(() -> webView.evaluateJavascript("window.__sxPhone&&window.__sxPhone.onNative(" + JSONObject.quote(event) + ")", null));
    }

    void onPermissionResult(int requestCode) {
        if ((requestCode == REQUEST_AUDIO || requestCode == REQUEST_NOTIFY) && pendingReply != null) {
            if (requestCode == REQUEST_NOTIFY) RecordingWatchWorker.setWatching(activity, true);
            reply(pendingReply, pendingId, status());
            pendingReply = null;
            pendingId = null;
        }
    }

    private void handle(String raw, JavaScriptReplyProxy reply) {
        String id = null;
        try {
            JSONObject message = new JSONObject(raw);
            id = message.optString("id");
            JSONObject args = message.optJSONObject("args");
            if (args == null) args = new JSONObject();
            switch (message.optString("method")) {
                case "status":
                    reply(reply, id, status());
                    break;
                case "requestAccess":
                    requestAccess(reply, id);
                    break;
                case "openAllFiles":
                    openAllFilesSettings();
                    reply(reply, id, status());
                    break;
                case "list":
                    list(reply, id, args.optInt("limit", 200));
                    break;
                case "read":
                    read(reply, id, args.optString("source"), args.optLong("offset", 0));
                    break;
                case "setWatch":
                    setWatch(reply, id, args.optBoolean("on"));
                    break;
                case "consumeLaunch": {
                    JSONObject result = new JSONObject();
                    result.put("source", launchSource == null ? JSONObject.NULL : launchSource);
                    launchSource = null;
                    reply(reply, id, result);
                    break;
                }
                default:
                    fail(reply, id, "unknown_method");
            }
        } catch (JSONException error) {
            fail(reply, id, "bad_message");
        }
    }

    private JSONObject status() {
        JSONObject status = new JSONObject();
        try {
            status.put("platform", "android");
            status.put("sdk", Build.VERSION.SDK_INT);
            status.put("audio", RecordingScanner.hasAudioAccess(activity));
            status.put("allFiles", RecordingScanner.hasAllFilesAccess());
            status.put("allFilesSupported", Build.VERSION.SDK_INT >= 30);
            status.put("notifications", notificationsAllowed());
            status.put("watching", RecordingWatchWorker.watching(activity));
            status.put("version", versionName());
        } catch (JSONException ignored) {}
        return status;
    }

    private String versionName() {
        try {
            return activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException error) {
            return "";
        }
    }

    private boolean notificationsAllowed() {
        return (
            Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        );
    }

    private void requestAccess(JavaScriptReplyProxy reply, String id) {
        if (RecordingScanner.hasAudioAccess(activity)) {
            reply(reply, id, status());
            return;
        }
        pendingReply = reply;
        pendingId = id;
        String permission = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_AUDIO : Manifest.permission.READ_EXTERNAL_STORAGE;
        ActivityCompat.requestPermissions(activity, new String[] { permission }, REQUEST_AUDIO);
    }

    private void setWatch(JavaScriptReplyProxy reply, String id, boolean on) {
        if (on && !notificationsAllowed()) {
            pendingReply = reply;
            pendingId = id;
            ActivityCompat.requestPermissions(activity, new String[] { Manifest.permission.POST_NOTIFICATIONS }, REQUEST_NOTIFY);
            return;
        }
        RecordingWatchWorker.setWatching(activity, on);
        reply(reply, id, status());
    }

    private void openAllFilesSettings() {
        if (Build.VERSION.SDK_INT < 30) return;
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
            intent.setData(Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(intent);
        } catch (RuntimeException error) {
            activity.startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        }
    }

    private void list(JavaScriptReplyProxy reply, String id, int limit) {
        io.execute(() -> {
            JSONObject result = new JSONObject();
            try {
                result.put("items", RecordingScanner.toJson(RecordingScanner.list(activity, Math.max(1, Math.min(limit, 500)))));
            } catch (JSONException ignored) {}
            reply(reply, id, result);
        });
    }

    private void read(JavaScriptReplyProxy reply, String id, String source, long offset) {
        io.execute(() -> {
            try (InputStream stream = RecordingScanner.open(activity, source)) {
                long skipped = 0;
                while (skipped < offset) {
                    long step = stream.skip(offset - skipped);
                    if (step <= 0) break;
                    skipped += step;
                }
                ByteArrayOutputStream out = new ByteArrayOutputStream(CHUNK);
                byte[] buffer = new byte[64 * 1024];
                int total = 0;
                int count;
                while (total < CHUNK && (count = stream.read(buffer, 0, Math.min(buffer.length, CHUNK - total))) > 0) {
                    out.write(buffer, 0, count);
                    total += count;
                }
                boolean eof = total < CHUNK || stream.read() < 0;
                JSONObject result = new JSONObject();
                result.put("data", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP));
                result.put("eof", eof);
                reply(reply, id, result);
            } catch (IOException | JSONException | RuntimeException error) {
                fail(reply, id, "read_failed");
            }
        });
    }

    private void reply(JavaScriptReplyProxy proxy, String id, JSONObject result) {
        JSONObject message = new JSONObject();
        try {
            message.put("id", id);
            message.put("ok", true);
            message.put("result", result);
        } catch (JSONException ignored) {}
        main.post(() -> proxy.postMessage(message.toString()));
    }

    private void fail(JavaScriptReplyProxy proxy, String id, String code) {
        JSONObject message = new JSONObject();
        try {
            message.put("id", id == null ? JSONObject.NULL : id);
            message.put("ok", false);
            message.put("error", code);
        } catch (JSONException ignored) {}
        main.post(() -> proxy.postMessage(message.toString()));
    }

    private String asset(String name) {
        try (InputStream stream = activity.getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int count;
            while ((count = stream.read(buffer)) > 0) out.write(buffer, 0, count);
            return out.toString(StandardCharsets.UTF_8.name());
        } catch (IOException error) {
            return null;
        }
    }
}
