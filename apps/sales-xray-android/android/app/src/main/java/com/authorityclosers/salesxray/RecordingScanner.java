package com.authorityclosers.salesxray;

import android.Manifest;
import android.content.ContentUris;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import androidx.core.content.ContextCompat;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Finds the call recordings a phone makes by itself (Samsung, Xiaomi, OnePlus,
 * Realme, Oppo, Vivo, Motorola and others save them as ordinary audio files).
 * Nothing leaves the phone here; the web app uploads only what the person picks.
 */
final class RecordingScanner {

    /** Folder names the built-in phone apps use, relative to shared storage. */
    static final String[] KNOWN_FOLDERS = {
        "Recordings/Call",
        "Recordings/Call recordings",
        "Recordings/Call Recordings",
        "Recordings/PhoneRecord",
        "Music/Recordings/Call Recordings",
        "MIUI/sound_recorder/call_rec",
        "Record/Call",
        "Record/PhoneRecord",
        "PhoneRecord",
        "Call",
        "CallRecordings",
        "Call Recordings",
        "Sounds/CallRecord",
    };

    /** Path fragments that mark a call-recorder folder in the media index. */
    private static final String[] PATH_HINTS = { "%call%", "%phonerecord%", "%call_rec%", "%callrecord%" };

    private static final Set<String> AUDIO = new HashSet<>(
        Arrays.asList("m4a", "mp3", "mpeg", "aac", "amr", "awb", "wav", "3gp", "ogg", "opus", "flac")
    );

    /** Formats the Sales Xray upload accepts today. */
    private static final Set<String> SUPPORTED = new HashSet<>(Arrays.asList("m4a", "mp3", "mpeg", "wav", "ogg", "flac"));

    private static final String[] SKIP = { "whatsapp", "telegram", "signal", "notification", "ringtone", "alarm" };

    private RecordingScanner() {}

    static boolean hasAudioAccess(Context context) {
        String permission = Build.VERSION.SDK_INT >= 33
            ? Manifest.permission.READ_MEDIA_AUDIO
            : Manifest.permission.READ_EXTERNAL_STORAGE;
        return ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED;
    }

    static boolean hasAllFilesAccess() {
        return Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager();
    }

    /** Newest first, at most {@code limit} items. */
    static List<JSONObject> list(Context context, int limit) {
        List<JSONObject> found = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        if (hasAudioAccess(context) || hasAllFilesAccess()) fromMediaIndex(context, found, seen);
        // Some phones hide the call folder from the media index (.nomedia);
        // with full file access the folders are read directly.
        if (hasAllFilesAccess() || (Build.VERSION.SDK_INT < 29 && hasAudioAccess(context))) fromFolders(found, seen);
        found.sort((a, b) -> Long.compare(b.optLong("addedMs"), a.optLong("addedMs")));
        return found.size() > limit ? new ArrayList<>(found.subList(0, limit)) : found;
    }

    static JSONArray toJson(List<JSONObject> items) {
        JSONArray array = new JSONArray();
        for (JSONObject item : items) array.put(item);
        return array;
    }

    private static void fromMediaIndex(Context context, List<JSONObject> found, Set<String> seen) {
        Uri collection = Build.VERSION.SDK_INT >= 29
            ? MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
            : MediaStore.Audio.Media.EXTERNAL_CONTENT_URI;
        String pathColumn = Build.VERSION.SDK_INT >= 29 ? MediaStore.MediaColumns.RELATIVE_PATH : MediaStore.MediaColumns.DATA;
        String[] projection = {
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
            pathColumn,
            MediaStore.MediaColumns.DATE_ADDED,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.MIME_TYPE,
            "duration",
        };
        StringBuilder selection = new StringBuilder("(");
        for (int i = 0; i < PATH_HINTS.length; i++) {
            if (i > 0) selection.append(" OR ");
            selection.append("LOWER(").append(pathColumn).append(") LIKE ?");
        }
        selection.append(")");
        try (
            Cursor cursor = context
                .getContentResolver()
                .query(collection, projection, selection.toString(), PATH_HINTS, MediaStore.MediaColumns.DATE_ADDED + " DESC")
        ) {
            if (cursor == null) return;
            while (cursor.moveToNext() && found.size() < 500) {
                long id = cursor.getLong(0);
                String name = cursor.getString(1);
                String folder = cursor.getString(2);
                if (name == null || skip(folder) || !AUDIO.contains(extension(name))) continue;
                long size = cursor.getLong(4);
                if (!seen.add(name.toLowerCase(Locale.ROOT) + ":" + size)) continue;
                Uri uri = ContentUris.withAppendedId(collection, id);
                found.add(item("media:" + uri, name, folderLabel(folder), cursor.getLong(3) * 1000L, cursor.getLong(6), size, cursor.getString(5)));
            }
        } catch (RuntimeException ignored) {
            // A phone without a media index, or a revoked permission: show nothing.
        }
    }

    private static void fromFolders(List<JSONObject> found, Set<String> seen) {
        File root = Environment.getExternalStorageDirectory();
        for (String relative : KNOWN_FOLDERS) {
            File folder = new File(root, relative);
            File[] files = folder.listFiles();
            if (files == null) continue;
            for (File file : files) {
                if (!file.isFile() || !AUDIO.contains(extension(file.getName()))) continue;
                if (!seen.add(file.getName().toLowerCase(Locale.ROOT) + ":" + file.length())) continue;
                found.add(item("file:" + file.getAbsolutePath(), file.getName(), relative, file.lastModified(), 0, file.length(), null));
            }
        }
    }

    private static JSONObject item(String source, String name, String folder, long addedMs, long durationMs, long size, String mime) {
        JSONObject json = new JSONObject();
        String ext = extension(name);
        try {
            json.put("source", source);
            json.put("name", name);
            json.put("title", title(name));
            json.put("folder", folder);
            json.put("addedMs", addedMs);
            json.put("durationMs", durationMs);
            json.put("size", size);
            json.put("ext", ext);
            json.put("mime", mime != null ? mime : mimeFor(ext));
            json.put("supported", SUPPORTED.contains(ext));
        } catch (JSONException ignored) {}
        return json;
    }

    /** "Call recording Ravi Sharma_241005_101530.m4a" becomes "Ravi Sharma". */
    static String title(String name) {
        String base = name.replaceFirst("\\.[^.]+$", "");
        base = base.replaceAll("(?i)^(call ?recording|call_rec|record|callrecord)[ _-]*", "");
        base = base.replaceAll("[_-]?\\d{6,}([_-]\\d{4,6})*$", "");
        base = base.replace('_', ' ').trim();
        return base.isEmpty() ? "Call recording" : base;
    }

    private static boolean skip(String folder) {
        if (folder == null) return false;
        String lower = folder.toLowerCase(Locale.ROOT);
        for (String word : SKIP) if (lower.contains(word)) return true;
        return false;
    }

    private static String folderLabel(String folder) {
        if (folder == null) return "";
        String trimmed = folder.replaceAll("/+$", "");
        int storage = trimmed.indexOf("/0/");
        return storage >= 0 ? trimmed.substring(storage + 3) : trimmed;
    }

    static String extension(String name) {
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    private static String mimeFor(String ext) {
        switch (ext) {
            case "m4a":
                return "audio/mp4";
            case "mp3":
            case "mpeg":
                return "audio/mpeg";
            case "wav":
                return "audio/wav";
            case "ogg":
            case "opus":
                return "audio/ogg";
            case "flac":
                return "audio/flac";
            case "aac":
                return "audio/aac";
            case "amr":
                return "audio/amr";
            case "3gp":
                return "audio/3gpp";
            default:
                return "application/octet-stream";
        }
    }

    static InputStream open(Context context, String source) throws IOException {
        if (source.startsWith("media:")) {
            Uri uri = Uri.parse(source.substring(6));
            // Only the shared audio index, never contacts, calls or other providers.
            if (!"media".equals(uri.getAuthority()) || !uri.getPath().contains("/audio/media/")) {
                throw new IOException("recording_not_allowed");
            }
            InputStream stream = context.getContentResolver().openInputStream(uri);
            if (stream == null) throw new IOException("recording_unavailable");
            return stream;
        }
        if (source.startsWith("file:")) {
            File file = new File(source.substring(5));
            // Only files inside the known call-recorder folders may be read.
            String path = file.getCanonicalPath();
            File root = Environment.getExternalStorageDirectory();
            for (String relative : KNOWN_FOLDERS) {
                if (path.startsWith(new File(root, relative).getCanonicalPath() + File.separator)) return new FileInputStream(file);
            }
        }
        throw new IOException("recording_not_allowed");
    }
}
