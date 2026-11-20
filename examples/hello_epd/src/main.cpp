// Minimal screen test for the CrowPanel 2.13" (SSD1680) using GxEPD2.
#include <Arduino.h>
#include <SPI.h>
#include <GxEPD2_BW.h>
#include <Fonts/FreeSansBold12pt7b.h>

// CS, DC, RST, BUSY
GxEPD2_BW<GxEPD2_213_GDEY0213B74, GxEPD2_213_GDEY0213B74::HEIGHT>
    display(GxEPD2_213_GDEY0213B74(14, 13, 10, 9));

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("hello_epd start");

  pinMode(7, OUTPUT);       // panel power
  digitalWrite(7, HIGH);
  delay(100);

  SPI.begin(12, -1, 11, 14);  // SCK, MISO, MOSI, SS
  display.epd2.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(115200, true, 10, false);  // prints BUSY timing to Serial

  display.setRotation(1);
  display.setFont(&FreeSansBold12pt7b);
  display.setTextColor(GxEPD_BLACK);
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.drawRect(3, 3, display.width() - 6, display.height() - 6, GxEPD_BLACK);
    display.setCursor(30, 70);
    display.print("Hello, Oz!");
  } while (display.nextPage());

  display.hibernate();
  Serial.println("hello_epd done");
}

void loop() {}
