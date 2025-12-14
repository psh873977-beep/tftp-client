#!/usr/bin/python
import socket
import argparse
import sys
import os
from struct import pack


DEFAULT_PORT = 69
BLOCK_SIZE = 512
DEFAULT_TRANSFER_MODE = 'octet'
TIME_OUT = 5  
MAX_TRY = 3 

OPCODE = {'RRQ': 1, 'WRQ': 2, 'DATA': 3, 'ACK': 4, 'ERROR': 5}
ERROR_CODE = {
    0: "Not defined.",
    1: "File not found.",
    2: "Access violation.",
    3: "Disk full.",
    4: "Illegal TFTP operation.",
    5: "Unknown transfer ID.",
    6: "File already exists.",
    7: "No such user."
}


def send_rrq(sock, address, filename, mode):
    """ Read Request (GET) 패킷 전송 """
    format_str = f'>h{len(filename)}sB{len(mode)}sB'
    rrq_message = pack(format_str, OPCODE['RRQ'], bytes(filename, 'utf-8'), 0, bytes(mode, 'utf-8'), 0)
    sock.sendto(rrq_message, address)
    # print(f"[DEBUG] Sent RRQ for {filename}")


def send_wrq(sock, address, filename, mode):
    """ Write Request (PUT) 패킷 전송 """
    format_str = f'>h{len(filename)}sB{len(mode)}sB'
    wrq_message = pack(format_str, OPCODE['WRQ'], bytes(filename, 'utf-8'), 0, bytes(mode, 'utf-8'), 0)
    sock.sendto(wrq_message, address)
    # print(f"[DEBUG] Sent WRQ for {filename}")


def send_ack(sock, address, block_num):
    """ ACK 패킷 전송 """
    ack_message = pack('>hh', OPCODE['ACK'], block_num)
    sock.sendto(ack_message, address)
    # print(f"[DEBUG] Sent ACK for block {block_num}")


def send_data(sock, address, block_num, data):
    """ DATA 패킷 전송 """
    format_str = f'>hh{len(data)}s'
    data_message = pack(format_str, OPCODE['DATA'], block_num, data)
    sock.sendto(data_message, address)



if __name__ == '__main__':
   
    parser = argparse.ArgumentParser(description='TFTP Client')
    parser.add_argument("host", help="Server IP or Domain name")
    parser.add_argument("operation", choices=['get', 'put'], help="Operation: get or put")
    parser.add_argument("filename", help="Filename to transfer")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help="Server Port")

    args = parser.parse_args()

   
    try:
        server_ip = socket.gethostbyname(args.host)
        print(f"Connecting to {args.host} ({server_ip})...")
    except socket.gaierror:
        print(f"Error: Invalid hostname '{args.host}'")
        sys.exit(1)

    server_port = args.port
    server_address = (server_ip, server_port)

    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIME_OUT)

    mode = DEFAULT_TRANSFER_MODE
    operation = args.operation
    filename = args.filename

    
    if operation == 'get':
        if os.path.exists(filename):
            print(f"Error: '{filename}' already exists locally.")
            sys.exit(1)

        try:
            file = open(filename, 'wb')
        except IOError as e:
            print(f"Error opening file: {e}")
            sys.exit(1)

        received_first_packet = False
        for try_count in range(MAX_TRY):
            send_rrq(sock, server_address, filename, mode)
            try:
                data, new_address = sock.recvfrom(516)
                server_address = new_address  
                received_first_packet = True
                break
            except socket.timeout:
                print(f"Timeout... Retrying ({try_count + 1}/{MAX_TRY})")

        if not received_first_packet:
            print("Error: Server not responding.")
            file.close()
            os.remove(filename)
            sys.exit(1)

       
        expected_block = 1
        while True:
            opcode = int.from_bytes(data[:2], 'big')

            if opcode == OPCODE['DATA']:
                block_number = int.from_bytes(data[2:4], 'big')
                if block_number == expected_block:
                    file_data = data[4:]
                    file.write(file_data)
                    send_ack(sock, server_address, block_number)
                    expected_block += 1

                    if len(file_data) < BLOCK_SIZE:
                        print(f"Download '{filename}' completed.")
                        break
                else:
                    send_ack(sock, server_address, block_number)

            elif opcode == OPCODE['ERROR']:
                error_code = int.from_bytes(data[2:4], 'big')
                err_msg = data[4:-1].decode('utf-8', errors='ignore')
                print(f"TFTP Error {error_code}: {ERROR_CODE.get(error_code, 'Unknown')} ({err_msg})")
                file.close()
                os.remove(filename)
                sys.exit(1)

            try:
                data, _ = sock.recvfrom(516)
            except socket.timeout:
                print("Timeout waiting for data. Exiting.")
                break

        file.close()

   
    elif operation == 'put':
        if not os.path.exists(filename):
            print(f"Error: File '{filename}' not found.")
            sys.exit(1)

        try:
            file = open(filename, 'rb')
        except IOError as e:
            print(f"Error opening file: {e}")
            sys.exit(1)

        received_ack0 = False
        for try_count in range(MAX_TRY):
            send_wrq(sock, server_address, filename, mode)
            try:
                data, new_address = sock.recvfrom(516)
                server_address = new_address
                opcode = int.from_bytes(data[:2], 'big')

                if opcode == OPCODE['ACK'] and int.from_bytes(data[2:4], 'big') == 0:
                    received_ack0 = True
                    break
                elif opcode == OPCODE['ERROR']:
                    error_code = int.from_bytes(data[2:4], 'big')
                    print(f"TFTP Error {error_code}: {ERROR_CODE.get(error_code, 'Unknown')}")
                    sys.exit(1)
            except socket.timeout:
                print(f"Timeout... Retrying ({try_count + 1}/{MAX_TRY})")

        if not received_ack0:
            print("Error: Server not responding or Protocol Error.")
            sys.exit(1)

        block_number = 1
        while True:
            file_block = file.read(BLOCK_SIZE)

            ack_received = False
            for try_count in range(MAX_TRY):
                send_data(sock, server_address, block_number, file_block)

                try:
                    data, _ = sock.recvfrom(516)
                    opcode = int.from_bytes(data[:2], 'big')

                    if opcode == OPCODE['ACK']:
                        if int.from_bytes(data[2:4], 'big') == block_number:
                            ack_received = True
                            break
                    elif opcode == OPCODE['ERROR']:
                        error_code = int.from_bytes(data[2:4], 'big')
                        print(f"TFTP Error {error_code}: {ERROR_CODE.get(error_code, 'Unknown')}")
                        file.close()
                        sys.exit(1)
                except socket.timeout:
                    print(f"Timeout waiting for ACK {block_number}. Retrying...")

            if not ack_received:
                print("Transfer failed: Max retries exceeded.")
                break

            block_number += 1
            if len(file_block) < BLOCK_SIZE:
                print(f"Upload '{filename}' completed.")
                break

        file.close()


    sock.close()
