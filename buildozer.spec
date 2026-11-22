[app]
title = SYNORA
package.name = synora
package.domain = org.synora
source.dir = client
source.include_exts = py,kv,ttf,json
version = 1.0
requirements = python3,kivy==2.3.0,openssl,cryptography,websocket-client,certifi,arabic-reshaper==3.0.0,python-bidi==0.4.2,six
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.archs = arm64-v8a

[buildozer]
log_level = 2
