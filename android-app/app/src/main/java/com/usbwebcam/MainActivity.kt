package com.usbwebcam

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

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

        val btnStart = findViewById<Button>(R.id.btn_start)
        val btnStop = findViewById<Button>(R.id.btn_stop)
        val btnCapture = findViewById<Button>(R.id.btn_capture)
        val tvStatus = findViewById<TextView>(R.id.tv_status)

        btnStart.setOnClickListener {
            if (checkPermission()) {
                startCamera()
            }
        }

        btnStop.setOnClickListener {
            stopCamera()
        }

        btnCapture.setOnClickListener {
            cameraHelper?.captureAndSave()
            Toast.makeText(this, "图片已保存到相册", Toast.LENGTH_SHORT).show()
        }

        // 自动启动
        if (checkPermission()) {
            startCamera()
        }
    }

    private fun checkPermission(): Boolean {
        return if (ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            true
        } else {
            requestPermissionLauncher.launch(Manifest.permission.CAMERA)
            false
        }
    }

    private fun startCamera() {
        cameraHelper = CameraHelper(this) { frame, _, _ ->
            mjpegServer?.updateFrame(frame)
        }

        mjpegServer = MjpegServer(8080)
        mjpegServer?.start {
            runOnUiThread {
                findViewById<TextView>(R.id.tv_status).text =
                    "服务运行中端口: 8080IP: 无需IP (ADB模式)USB连接命令:adb forward tcp:8080 tcp:8080"
                findViewById<Button>(R.id.btn_start).isEnabled = false
                findViewById<Button>(R.id.btn_stop).isEnabled = true
            }
        }

        cameraHelper?.start()
    }

    private fun stopCamera() {
        cameraHelper?.stop()
        mjpegServer?.stop()

        findViewById<TextView>(R.id.tv_status).text = "服务已停止"
        findViewById<Button>(R.id.btn_start).isEnabled = true
        findViewById<Button>(R.id.btn_stop).isEnabled = false
    }

    override fun onDestroy() {
        super.onDestroy()
        stopCamera()
    }
}
