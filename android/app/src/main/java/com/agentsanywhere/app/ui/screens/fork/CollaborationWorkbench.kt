package com.agentsanywhere.app.ui.screens.fork

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.agentsanywhere.app.feature.fork.WorkbenchSession
import com.agentsanywhere.app.feature.fork.workbenchAllowsNavigation
import org.json.JSONObject

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun CollaborationWorkbench(session: WorkbenchSession, onClose: () -> Unit) {
    var webView by remember(session) { mutableStateOf<WebView?>(null) }
    var chooser by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        chooser?.onReceiveValue(uris.takeIf { it.isNotEmpty() }?.toTypedArray()); chooser = null
    }
    DisposableEffect(session) {
        onDispose {
            chooser?.onReceiveValue(null); chooser = null
            webView?.let { view ->
                view.stopLoading()
                view.evaluateJavascript("localStorage.removeItem('aa.session.v1')") { view.destroy() }
            }
        }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            Column {
                TextButton(onClick = onClose) { Text("返回原生会话") }
                if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
                    Text("请更新 Android System WebView 后使用多 AI 工作台。")
                } else AndroidView(modifier = Modifier.weight(1f).fillMaxWidth(), factory = { context ->
                    WebView(context).apply {
                        webView = this
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        settings.allowFileAccess = false
                        settings.allowContentAccess = true
                        settings.setSupportMultipleWindows(false)
                        WebViewCompat.addDocumentStartJavaScript(this,
                            "if(window.top===window && location.origin===" + JSONObject.quote(session.origin) + ") localStorage.setItem('aa.session.v1'," + JSONObject.quote(session.sessionJson) + ");",
                            setOf(session.origin))
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                                !workbenchAllowsNavigation(session.origin, request.url.toString())
                        }
                        webChromeClient = object : WebChromeClient() {
                            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                                chooser?.onReceiveValue(null)
                                chooser = callback
                                picker.launch(params.acceptTypes.filter { it.isNotBlank() }.toTypedArray().takeIf { it.isNotEmpty() } ?: arrayOf("*/*"))
                                return true
                            }
                        }
                        loadUrl(session.origin)
                    }
                })
            }
        }
        BackHandler { if (webView?.canGoBack() == true) webView?.goBack() else onClose() }
    }
}
