#!/bin/bash 

sudo apt install python3-venv bluez bluez-tools
rm -rf venv 
python3 -m venv venv
source venv/bin/activate 
pip install --upgrade pip 
pip install -r requirements.txt 
