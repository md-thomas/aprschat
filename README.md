# README
This is my attempt at creating an aprs chat service. 
This uses flask as the backend for the html front end 

# INSTALL
Requirements: python3 and some python modules
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

Once the application is running you can open a web 
page http://localhost:5001  or http://<your-ip-address:5001

The application runs on port 5000  

# Todo 
1. Keep last used callsign 
2. Add users callsign to page somewhere
3. Add version to page somewhere
4. Add warning if more than 67 characters used in message
5. maybe split messages larger than 67 characters into multiple messages 
6. create a group of callsigns to send messages to
7. add a map to show a location for users
8. add a send position button 



