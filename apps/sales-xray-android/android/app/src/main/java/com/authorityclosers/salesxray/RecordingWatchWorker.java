package com.authorityclosers.salesxray;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/**
 * Every 15 minutes, looks for call recordings the phone made since the last
 * look and offers them in a notification. Tapping it opens Sales Xray with
 * that recording ready to analyse. Nothing is uploaded from here.
 */
public class RecordingWatchWorker extends Worker {

    static final String WORK = "sx-recording-watch";
    static final String CHANNEL = "call_recordings";
    static final String EXTRA_SOURCE = "sx_recording_source";
    static final String PREFS = "sx_recordings";
    static final String WATCHING = "watching";
    static final String LAST_SEEN = "last_seen_ms";

    public RecordingWatchWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static void setWatching(Context context, boolean on) {
        // Start from now, so turning it on never floods old recordings.
        prefs(context).edit().putBoolean(WATCHING, on).putLong(LAST_SEEN, System.currentTimeMillis()).apply();
        WorkManager work = WorkManager.getInstance(context);
        if (on) {
            PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(RecordingWatchWorker.class, 15, TimeUnit.MINUTES).build();
            work.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, request);
        } else {
            work.cancelUniqueWork(WORK);
        }
    }

    static boolean watching(Context context) {
        return prefs(context).getBoolean(WATCHING, false);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        if (!watching(context)) return Result.success();
        long lastSeen = prefs(context).getLong(LAST_SEEN, System.currentTimeMillis());
        List<JSONObject> items = RecordingScanner.list(context, 50);
        long newest = lastSeen;
        JSONObject first = null;
        int count = 0;
        for (JSONObject item : items) {
            long added = item.optLong("addedMs");
            if (added <= lastSeen) continue;
            count++;
            if (first == null) first = item;
            newest = Math.max(newest, added);
        }
        if (count > 0) {
            prefs(context).edit().putLong(LAST_SEEN, newest).apply();
            notify(context, first, count);
        }
        return Result.success();
    }

    private static void notify(Context context, JSONObject first, int count) {
        if (
            Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "New call recordings", NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Tells you when your phone saved a call recording you can analyse.");
            manager.createNotificationChannel(channel);
        }
        Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (count == 1) open.putExtra(EXTRA_SOURCE, first.optString("source"));
        PendingIntent pending = PendingIntent.getActivity(
            context,
            1,
            open,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        String title = count == 1 ? "New call recording" : count + " new call recordings";
        String text = count == 1 ? first.optString("title") + " · tap to analyse in Sales Xray" : "Tap to choose which to analyse in Sales Xray";
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_recording)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT);
        try {
            NotificationManagerCompat.from(context).notify(42, builder.build());
        } catch (SecurityException ignored) {
            // Notifications were turned off after the check; nothing to do.
        }
    }
}
