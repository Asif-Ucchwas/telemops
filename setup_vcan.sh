#!/bin/bash
# Recreates the vcan0 virtual CAN interface — does not persist across WSL2 restarts.
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan 2>/dev/null || echo "vcan0 already exists"
sudo ip link set up vcan0
ip link show vcan0
