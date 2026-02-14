package com.usbwebcam

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.net.NetworkInterface

class MainActivity : AppCompatActivity() {
    private var mjpegServer: MjpegServer? = null
    private var cameraHelper: CameraHelper? = null

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            startCamera()
        } else {
            Toast.makeText(this, "需要相机权限", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<Button>(R.id.btn_start).setOnClickListener {
            if (checkPermission()) {
                startCamera()
            }
        }

        findViewById<Button>(R.id.btn_stop).setOnClickListener {
            stopCamera()
        }

        findViewById<Button>(R.id.btn_capture).setOnClickListener {
            val saved = cameraHelper?.captureAndSave() == true
            val msg = if (saved) "图片已保存到相册" else "保存失败，请先启动服务"
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        }

        if (ContextCompat.checkSelfPermission(
                this, Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        }
    }

    private fun checkPermission(): Boolean {
        return if (ContextCompat.checkSelfPermission(
                this, Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            true
        } else {
            requestPermissionLauncher.launch(Manifest.permission.CAMERA)
            false
        }
    }

    private fun getDeviceIp(): String {
        try {
            NetworkInterface.getNetworkInterfaces()?.toList()?.forEach { intf ->
                intf.inetAddresses?.toList()?.forEach { addr ->
                    if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                        return addr.hostAddress ?: "未知"
                    }
                }
            }
        } catch (_: Exception) {}
        return "未知"
    }

    private fun startCamera() {
        if (cameraHelper != null) return

        mjpegServer = MjpegServer(8080)
        cameraHelper = CameraHelper(this) { frame, _, _ ->
            mjpegServer?.updateFrame(frame)
        }

        mjpegServer?.start {
            runOnUiThread {
                val ip = getDeviceIp()
                findViewById<TextView>(R.id.tv_status).text =
                    "● 服务运行中\n\n" +
                    "端口: 8080\n" +
                    "设备IP: $ip\n\n" +
                    "USB连接 (推荐):\n" +
                    "  adb forward tcp:8080 tcp:8080\n\n" +
                    "WiFi连接:\n" +
                    "  http://$ip:8080"

                findViewById<TextView>(R.id.tv_ip).apply {
                    text = "在电脑端浏览器打开上述地址即可查看画面"
                    visibility = View.VISIBLE
                }
                findViewById<TextView>(R.id.tv_indicator).apply {
                    text = "● 运行中"
                    setTextColor(getColor(R.color.status_running))
                }
                findViewById<Button>(R.id.btn_start).isEnabled = false
                findViewById<Button>(R.id.btn_stop).isEnabled = true
            }
        }

        cameraHelper?.start()
    }

    private fun stopCamera() {
        cameraHelper?.stop()
        cameraHelper = null
        mjpegServer?.stop()
        mjpegServer = null

        runOnUiThread {
            findViewById<TextView>(R.id.tv_status).text = "服务已停止"
            findViewById<TextView>(R.id.tv_ip).visibility = View.GONE
            findViewById<TextView>(R.id.tv_indicator).apply {
                text = "⏸ 未启动"
                setTextColor(getColor(R.color.status_stopped))
            }
            findViewById<Button>(R.id.btn_start).isEnabled = true
            findViewById<Button>(R.id.btn_stop).isEnabled = false
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopCamera()
    }
}
