#!/bin/bash
# Automatically detects current Mac Wi-Fi/LAN IP and updates FreePBX
IP=$(ipconfig getifaddr en0 2>/dev/null)
if [ -z "$IP" ]; then
    IP=$(ipconfig getifaddr en1 2>/dev/null)
fi

if [ -z "$IP" ]; then
    echo "Error: Could not detect Mac IP address. Are you connected to Wi-Fi?"
    exit 1
fi

echo "Detected Mac IP: $IP"
echo "Updating Asterisk and FreePBX settings inside Docker..."

# Update Media Address for endpoint 6000
/usr/local/bin/docker exec freepbx sh -c "cat <<INNEREOF > /etc/asterisk/pjsip.endpoint_custom_post.conf
[6000](+)
media_address=$IP
rtp_timeout=0
rtp_timeout_hold=0
INNEREOF"

# Update SIP Signaling Address (externip) in FreePBX database
/usr/local/bin/docker exec freepbx mysql -u root -D asterisk -e "update kvstore_Sipsettings set val='$IP' where \`key\`='externip';"

echo "Reloading FreePBX (this may take a few seconds)..."
/usr/local/bin/docker exec freepbx fwconsole reload > /dev/null

echo "✅ Success! Asterisk Media and Signaling updated to $IP."
echo "You can now make calls from Zoiper without audio issues or 30s timeouts."
