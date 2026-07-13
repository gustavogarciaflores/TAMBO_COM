import socket
import struct
import time
import threading
import csv
import os

# ---------- CONFIGURACIÓN (20 bytes, 100 pkt/s, imagen 2000 bytes) ----------
UDP_PORT = 1234
PAYLOAD_SIZE = 20                           # payload de 20 bytes
STATS_INTERVAL = 5
IMG_SIZE = 2000                             # imagen de 2000 bytes (1 segundo)
CHUNKS_PER_IMAGE = (IMG_SIZE + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE   # 100
CSV_FILENAME = r"D:\Trabajo\TAMBO_project\Pruebas\Nodos\Nodo_prueba_20bytes_100pulsos\gateway_stats_20B_100pqts_1seg_pr2.csv"
# -----------------------------------------------------------

# Cargar imagen de referencia (solo los primeros IMG_SIZE bytes)
try:
    with open('imagen_color.bin', 'rb') as f:
        imagen_ref = f.read()
    print(f"Imagen de referencia cargada: {len(imagen_ref)} bytes")
    if len(imagen_ref) < IMG_SIZE:
        print(f"ERROR: el archivo tiene {len(imagen_ref)} bytes, menor que {IMG_SIZE}")
        exit(1)
    imagen_ref = imagen_ref[:IMG_SIZE]
    print(f"Usando los primeros {IMG_SIZE} bytes para comparación.")
except FileNotFoundError:
    print("ERROR: No se encuentra 'imagen_color.bin'. Colócalo en la misma carpeta.")
    exit(1)

# Formato del paquete: nodeId(B), seqNumber(H), battery(H), rssi(b), pulse(20s)
PACKET_FORMAT = '<BHHb' + f'{PAYLOAD_SIZE}s'
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)   # 26

class NodeStats:
    def _init_(self, node_id):
        self.node_id = node_id
        self.packets_recv = 0
        self.bytes_recv = 0
        self.lost_packets = 0
        self.last_seq = None
        self.first_packet = True
        self.rssi = 0
        self.connected = False
        self.ip = None
        self.last_battery = 0

        self.current_image_id = 0xFFFF
        self.correct_bytes_in_image = 0
        self.sum_integrity = 0.0
        self.images_completed = 0
        self.last_packet_time = time.time()
        self.first_pulse_printed = False   # para depuración

stats = {}
lock = threading.Lock()

def process_packet(data, addr):
    try:
        node_id, seq, battery, rssi, pulse = struct.unpack(PACKET_FORMAT, data)
    except struct.error:
        return

    now = time.time()
    with lock:
        if node_id not in stats:
            stats[node_id] = NodeStats(node_id)
            print(f'[+] Nodo {node_id} detectado ({addr[0]})')

        ns = stats[node_id]
        # ---- DEPURACIÓN: imprime los primeros 10 bytes del primer paquete recibido ----
        if not ns.first_pulse_printed and ns.packets_recv == 0:
            print(f"Primeros 10 bytes del pulso recibido (nodo {node_id}): {list(pulse[:10])}")
            ns.first_pulse_printed = True

        ns.packets_recv += 1
        ns.bytes_recv += len(data) + 28
        ns.last_battery = battery
        ns.rssi = rssi
        ns.last_packet_time = now
        ns.ip = addr[0]

        # Integridad de imagen
        image_id = seq // CHUNKS_PER_IMAGE
        chunk = seq % CHUNKS_PER_IMAGE

        if image_id != ns.current_image_id:
            if ns.current_image_id != 0xFFFF:
                integridad = (ns.correct_bytes_in_image * 100.0) / IMG_SIZE
                ns.sum_integrity += integridad
                ns.images_completed += 1
            ns.correct_bytes_in_image = 0
            ns.current_image_id = image_id

        base_global = chunk * PAYLOAD_SIZE
        bytes_to_check = PAYLOAD_SIZE
        if base_global + bytes_to_check > IMG_SIZE:
            bytes_to_check = IMG_SIZE - base_global

        for i in range(bytes_to_check):
            global_idx = base_global + i
            if pulse[i] == imagen_ref[global_idx]:
                ns.correct_bytes_in_image += 1

        # Pérdidas
        if ns.first_packet:
            ns.last_seq = seq
            ns.first_packet = False
        else:
            expected = ns.last_seq + 1
            diff = seq - expected
            if diff > 1000:
                ns.first_packet = True
            else:
                ns.lost_packets += diff
            ns.last_seq = seq

def print_stats():
    while True:
        time.sleep(STATS_INTERVAL)
        now = time.time()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        with lock:
            rows = []
            for node_id in sorted(stats.keys()):
                ns = stats[node_id]
                ns.connected = (now - ns.last_packet_time) < 7.0
                elapsed = STATS_INTERVAL
                pps = ns.packets_recv / elapsed if elapsed > 0 else 0
                tp_kbps = (ns.bytes_recv / elapsed) / 1024.0 if elapsed > 0 else 0
                total = ns.packets_recv + ns.lost_packets
                eff = (100.0 * ns.packets_recv / total) if total > 0 else 0.0
                avg_integrity = (ns.sum_integrity / ns.images_completed) if ns.images_completed > 0 else 0.0
                dist = 9.0

                rows.append([timestamp, ns.node_id,
                             ns.rssi if ns.connected else 0,
                             dist, ns.last_battery, pps, tp_kbps,
                             ns.lost_packets, eff, avg_integrity])

                # Reiniciar contadores
                ns.packets_recv = 0
                ns.bytes_recv = 0
                ns.lost_packets = 0
                ns.sum_integrity = 0.0
                ns.images_completed = 0

            # ---- Guardar en CSV ----
            try:
                file_exists = os.path.isfile(CSV_FILENAME) and os.path.getsize(CSV_FILENAME) > 0
                with open(CSV_FILENAME, 'a', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    if not file_exists:
                        writer.writerow(["Timestamp", "NodeID", "RSSI(dBm)", "Dist(m)",
                                         "Bat(mV)", "Pkts/s", "KB/s", "Perdidos",
                                         "Eficiencia(%)", "Integridad(%)"])
                    for row in rows:
                        formatted_row = [row[0], row[1], row[2],
                                         f"{row[3]:.2f}", row[4],
                                         f"{row[5]:.2f}", f"{row[6]:.2f}",
                                         row[7], f"{row[8]:.2f}", f"{row[9]:.2f}"]
                        writer.writerow(formatted_row)
            except Exception as e:
                print(f"Error al escribir CSV: {e}")

            # ---- Imprimir en terminal ----
            print("\n" + "=" * 90)
            print("ID | RSSI(dBm) | Dist(m) | Bat(mV) | Pkts/s | KB/s | Perdidos | Eficiencia(%) | Integridad(%)")
            print("---|-----------|---------|---------|--------|------|----------|--------------|--------------")
            for row in rows:
                timestamp_str, node_id, rssi, dist, bat, pps, kbps, lost, eff, integ = row
                print(f"{node_id:2d} | {rssi:4d} dBm | {dist:6.2f} | {bat:4d} mV | {pps:5.0f} | {kbps:4.2f} | "
                      f"{lost:8d} | {eff:6.2f} | {integ:10.1f}")
            print("=" * 90)

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', UDP_PORT))
    print(f"Gateway UDP escuchando en 0.0.0.0:{UDP_PORT}")
    print("Esperando paquetes de los nodos...")

    printer = threading.Thread(target=print_stats, daemon=True)
    printer.start()

    try:
        while True:
            data, addr = sock.recvfrom(65535)
            if len(data) == PACKET_SIZE:
                process_packet(data, addr)
    except KeyboardInterrupt:
        print("\nCerrando...")
        sock.close()

if _name_ == '_main_':
    main()
