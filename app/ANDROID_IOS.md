# Configurazione della piattaforma (una volta)

Dopo `setup.bat` (Windows) o `setup.sh` (Mac/Linux), che creano le cartelle `android/` e `ios/`:

## Android — `android/app/src/main/AndroidManifest.xml`
Dentro `<manifest>`, prima di `<application>`:
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.CAMERA"/>
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>
<queries>
  <intent><action android:name="android.intent.action.VIEW"/><data android:scheme="https"/></intent>
</queries>
```
Solo per provare con un server in casa SENZA https, aggiungi a `<application ...>`: `android:usesCleartextTraffic="true"`.
In produzione usa https e non aggiungerlo.

## iOS — `ios/Runner/Info.plist`
```xml
<key>NSCameraUsageDescription</key><string>Serve per leggere il codice a barre.</string>
<key>NSLocationWhenInUseUsageDescription</key><string>Serve per trovare i negozi vicini.</string>
```

## Primo avvio
L'app apre le Impostazioni: scrivi l'indirizzo del servizio (es. `https://il-tuo-server`) e premi "Salva e prova".
