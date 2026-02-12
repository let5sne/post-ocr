package com.usbwebcam

import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean

class MjpegServer(private val port: Int) {
    private var serverSocket: ServerSocket? = null
    private var serverThread: Thread? = null
    private val clients = CopyOnWriteArrayList<ClientHandler>()
    private val running = AtomicBoolean(false)
    private var currentFrame: ByteArray? = null
    private val frameLock = Any()

    fun start(onStarted: () -> Unit) {
        serverThread = Thread {
            try {
                serverSocket = ServerSocket(port)
                running.set(true)
                onStarted()

                while (running.get()) {
                    val client = try {
                        serverSocket?.accept()
                    } catch (e: Exception) {
                        null
                    } ?: continue

                    val handler = ClientHandler(client)
                    clients.add(handler)
                    handler.start()

                    // 发送当前帧
                    val frameToSend = synchronized(frameLock) {
                        currentFrame
                    }
                    if (frameToSend != null) {
                        handler.sendFrame(frameToSend)
                    }
                }
            } catch (e: Exception) {
                if (running.get()) {
                    e.printStackTrace()
                }
            }
        }.apply {
            name = "MjpegServerThread"
            start()
        }
    }

    fun updateFrame(frame: ByteArray) {
        synchronized(frameLock) {
            currentFrame = frame
        }

        // 广播给所有客户端
        val iterator = clients.iterator()
        while (iterator.hasNext()) {
            val handler = iterator.next()
            if (handler.isAlive()) {
                handler.sendFrame(frame)
            } else {
                iterator.remove()
            }
        }
    }

    fun stop() {
        if (!running.getAndSet(false)) return

        try {
            serverSocket?.close()
        } catch (e: Exception) {
            // ignore
        }

        clients.forEach { it.close() }
        clients.clear()
        serverSocket = null
        serverThread = null
    }

    private class ClientHandler(private val socket: Socket) : Thread() {
        private var clientStream: OutputStream? = null
        @Volatile
        private var initialized = false

        override fun run() {
            try {
                val os = socket.getOutputStream()
                clientStream = os
                socket.setSoTimeout(5000)

                // 读取HTTP请求
                val buffer = ByteArray(1024)
                socket.getInputStream().read(buffer)

                // 发送HTTP响应头
                val header = byteArrayOf(
                    *("HTTP/1.1 200 OK\r\n").toByteArray(),
                    *("Content-Type: multipart/x-mixed-replace; boundary=boundary\r\n").toByteArray(),
                    *("Cache-Control: no-cache\r\n").toByteArray(),
                    *("Connection: close\r\n").toByteArray(),
                    *("\r\n").toByteArray()
                )

                os.write(header)
                os.flush()
                initialized = true
            } catch (e: Exception) {
                close()
            }
        }

        fun sendFrame(frame: ByteArray) {
            if (!initialized) return

            try {
                // MJPEG frame header
                val header = byteArrayOf(
                    *("--boundary\r\n").toByteArray(),
                    *("Content-Type: image/jpeg\r\n").toByteArray(),
                    *("Content-Length: ${frame.size}\r\n").toByteArray(),
                    *("\r\n").toByteArray()
                )

                clientStream?.write(header)
                clientStream?.write(frame)
                clientStream?.write("\r\n".toByteArray())
                clientStream?.flush()
            } catch (e: Exception) {
                close()
            }
        }

        fun close() {
            try {
                socket.close()
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        fun isAlive(): Boolean {
            return !socket.isClosed && socket.isConnected
        }
    }
}
