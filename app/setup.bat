@echo off
flutter create . --project-name prezzi_vicini --org it.tuonome --platforms android,ios
flutter pub get
echo.
echo Ora configura i permessi come descritto in ANDROID_IOS.md
