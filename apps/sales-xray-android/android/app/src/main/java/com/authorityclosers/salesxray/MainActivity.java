package com.authorityclosers.salesxray;

import android.content.Intent;
import android.os.Bundle;
import android.webkit.WebView;
import androidx.annotation.NonNull;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebViewClient;

/** Sales Xray in a Capacitor shell, plus the phone's own call recordings. */
public class MainActivity extends BridgeActivity {

    private PhoneBridge phone;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        phone = new PhoneBridge(this, getBridge().getWebView());
        phone.attach();
        phone.takeLaunch(getIntent());
        getBridge()
            .setWebViewClient(
                new BridgeWebViewClient(getBridge()) {
                    @Override
                    public void onPageFinished(WebView view, String url) {
                        super.onPageFinished(view, url);
                        phone.inject(view, url);
                    }
                }
            );
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (phone == null) return;
        phone.takeLaunch(intent);
        phone.signal("launch");
    }

    @Override
    public void onResume() {
        super.onResume();
        if (phone != null) phone.signal("resume");
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (phone != null) phone.onPermissionResult(requestCode);
    }
}
