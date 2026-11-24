#!/usr/bin/env bash
set -e
flutter create . --project-name prezzi_vicini --org it.tuonome --platforms android,ios
flutter pub get
echo "Ora configura i permessi come descritto in ANDROID_IOS.md"
