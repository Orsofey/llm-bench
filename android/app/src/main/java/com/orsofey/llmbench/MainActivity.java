package com.orsofey.llmbench;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public final class MainActivity extends Activity {
    private static final int ACCENT = 0xFF9B87F5;
    private static final int TEXT_MAIN = 0xFFF5F3FF;
    private static final int TEXT_MUTED = 0xFFAAA6BD;
    private static final int TEXT_DIM = 0xFF716D84;

    private FrameLayout root;
    private WebView webView;
    private TextView statusView;
    private TextView errorView;
    private String baseUrl;
    private boolean webViewReady;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(0xF007070D);

        root = new FrameLayout(this);
        root.setBackgroundColor(0xFF07070D);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root);
        buildSplash();
        buildWebView();

        final String dataDir = getFilesDir().getAbsolutePath();
        new Thread(() -> {
            Throwable startupError = null;
            int port = 0;
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getApplicationContext()));
                }
                port = Python.getInstance().getModule("android_bridge")
                        .callAttr("start", dataDir).toInt();
            } catch (Throwable e) {
                startupError = e;
            }
            final int resultPort = port;
            final Throwable error = startupError;
            runOnUiThread(() -> {
                if (error == null) {
                    showApp("http://127.0.0.1:" + resultPort + "/");
                } else {
                    showError(error);
                }
            });
        }, "llm-bench-boot").start();
    }

    private void buildSplash() {
        LinearLayout loading = new LinearLayout(this);
        loading.setOrientation(LinearLayout.VERTICAL);
        loading.setGravity(Gravity.CENTER);
        loading.setPadding(56, 48, 56, 48);
        root.addView(loading, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        TextView brand = new TextView(this);
        brand.setText("LLM Bench");
        brand.setTextSize(34);
        brand.setTextColor(TEXT_MAIN);
        brand.setLetterSpacing(-0.04f);
        brand.setGravity(Gravity.CENTER);
        loading.addView(brand);

        TextView by = new TextView(this);
        by.setText("BY ORSOFEY");
        by.setTextSize(10);
        by.setTextColor(TEXT_DIM);
        by.setLetterSpacing(0.22f);
        by.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams byParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        byParams.topMargin = 10;
        loading.addView(by, byParams);

        ProgressBar progress = new ProgressBar(this);
        progress.setIndeterminate(true);
        progress.setIndeterminateTintList(ColorStateList.valueOf(ACCENT));
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        progressParams.topMargin = 30;
        loading.addView(progress, progressParams);

        statusView = new TextView(this);
        statusView.setText("Запускаю локальный движок…");
        statusView.setTextSize(12);
        statusView.setTextColor(TEXT_MUTED);
        statusView.setGravity(Gravity.CENTER);
        statusView.setLineSpacing(3, 1.05f);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        statusParams.topMargin = 13;
        loading.addView(statusView, statusParams);
    }

    private void buildWebView() {
        webView = new WebView(this);
        webView.setVisibility(View.GONE);
        webView.setBackgroundColor(Color.TRANSPARENT);
        root.addView(webView, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url != null && url.startsWith(baseUrl)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                webViewReady = true;
                webView.setVisibility(View.VISIBLE);
                webView.setAlpha(0f);
                webView.animate().alpha(1f).setDuration(220).start();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && request.isForMainFrame() && error != null) {
                    showError(new IllegalStateException(String.valueOf(error.getDescription())));
                }
            }
        });
    }

    private void showApp(String url) {
        if (baseUrl == null) {
            baseUrl = url;
            webView.loadUrl(url);
        }
    }

    private void showError(Throwable error) {
        android.util.Log.e("LLM Bench", "Engine startup failed", error);
        if (errorView == null) {
            errorView = new TextView(this);
            errorView.setTextColor(TEXT_MUTED);
            errorView.setTextSize(12);
            errorView.setLineSpacing(5, 1.25f);
            errorView.setPadding(42, 56, 42, 48);
            errorView.setTextIsSelectable(false);
            root.addView(errorView, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT));
        }
        if (webViewReady) {
            errorView.setText("Интерфейс загрузился, но локальный движок потерял соединение. Закройте приложение и откройте снова.\n\n"
                    + error.getMessage());
        } else {
            errorView.setText("Не удалось запустить локальный движок.\n\n"
                    + (error.getMessage() == null ? "неизвестная ошибка" : error.getMessage()));
        }
        errorView.setVisibility(View.VISIBLE);
        webView.setVisibility(View.GONE);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }
}
