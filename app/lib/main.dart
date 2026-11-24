import 'package:flutter/material.dart';
import 'screens/home_screen.dart';

void main() => runApp(const PrezziViciniApp());

class PrezziViciniApp extends StatelessWidget {
  const PrezziViciniApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Prezzi Vicini',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorSchemeSeed: const Color(0xFF0E7C66),
          useMaterial3: true,
        ),
        home: const HomeScreen(),
      );
}
