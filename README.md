# README
This is my attempt at creating an aprs chat service. 
This uses flask as the backend for the html front end 

# INSTALL
You need to run the install.sh script to setup the 
python virtual environment. This will install the 
needed python modules locally. 

# CONFIG 
Edit the aprschat.config file 
Enter your callsign and aprs passcode 
This url can be used to get your aprs passcode
https://apps.magicbug.co.uk/passcode/

# STARTUP
./start.sh will kick off the the flask backend server
that listens for messages being send and received on
the aprs network. 

