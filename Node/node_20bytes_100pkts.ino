#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>

const char* ssid       = "RedUDP";
const char* password   = "12345678";
const IPAddress gatewayIP(192, 168, 0, 100);   // IP fija de la PC
const uint16_t dataPort = 1234;
const uint8_t  nodeId   = 4;                  // Cambiar por el número de este nodo

#define PAYLOAD_SIZE 20
const unsigned long SEND_INTERVAL = 10;        // 100 pkt/s

typedef struct __attribute__((packed)) {
  uint8_t  nodeId;
  uint16_t seqNumber;
  uint16_t batteryVoltage;
  int8_t   rssi;
  uint8_t  pulse[PAYLOAD_SIZE];
} data_packet_t;

#include "imagen_color.h"   // Define imagen[] e IMG_REAL_SIZE (121203)

// Tamaño de la porción de imagen que estamos transmitiendo (2000 bytes = 1 segundo)
#define IMG_SIZE 2000
// Número de chunks necesario para cubrir IMG_SIZE con PAYLOAD_SIZE
#define CHUNKS_PER_IMAGE ((IMG_SIZE + PAYLOAD_SIZE - 1) / PAYLOAD_SIZE)   // 100

data_packet_t pkt;
WiFiUDP dataUdp;
uint16_t seq = 0;
unsigned long lastSend = 0;

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  esp_wifi_set_ps(WIFI_PS_NONE);

  while (WiFi.status() != WL_CONNECTED) { delay(500); }
  Serial.println("\nConectado. IP: " + WiFi.localIP().toString());
  pkt.nodeId = nodeId;
  pkt.batteryVoltage = 3300;

  // Mostrar la configuración actual
  Serial.printf("Payload: %d bytes, Chunks/imagen: %d, Intervalo: %lu ms\n",
                PAYLOAD_SIZE, CHUNKS_PER_IMAGE, SEND_INTERVAL);
}

void loop() {
  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();

    pkt.seqNumber = seq;
    pkt.rssi = (int8_t)WiFi.RSSI();

    uint16_t chunk = pkt.seqNumber % CHUNKS_PER_IMAGE;
    uint32_t offset = chunk * PAYLOAD_SIZE;
    uint16_t bytes_to_copy = PAYLOAD_SIZE;
    if (offset + bytes_to_copy > IMG_SIZE) {
      bytes_to_copy = IMG_SIZE - offset;       // último fragmento más corto (no sobra)
    }

    // Copiar solo los bytes válidos y rellenar el resto con ceros
    memcpy(pkt.pulse, &imagen[offset], bytes_to_copy);
    if (bytes_to_copy < PAYLOAD_SIZE) {
      memset(&pkt.pulse[bytes_to_copy], 0, PAYLOAD_SIZE - bytes_to_copy);
    }

    dataUdp.beginPacket(gatewayIP, dataPort);
    dataUdp.write((uint8_t*)&pkt, sizeof(pkt));
    dataUdp.endPacket();

    seq++;

    // Mensaje cada 100 imágenes (opcional)
    if (chunk == 0 && (seq / CHUNKS_PER_IMAGE) % 100 == 0) {
      Serial.printf("Inicio imagen %u\n", seq / CHUNKS_PER_IMAGE);
    }
  }
  delay(1);
}
