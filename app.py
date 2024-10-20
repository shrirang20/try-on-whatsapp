from flask import Flask, request, jsonify
import os
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from PIL import Image
import requests
import gradio_client
import tempfile
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Twilio credentials from environment variables
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app = Flask(__name__)

# Store user states (you might want to use a proper database in production)
user_states = {}

def process_try_on(person_image_path, garment_image_path):
    try:
        client = gradio_client.Client("Kwai-Kolors/Kolors-Virtual-Try-On")
        result = client.predict(
            person_image_path,
            garment_image_path,
            0,  # seed
            True,  # random seed
            api_name="/predict"
        )
        return result
    except Exception as e:
        print(f"Error in process_try_on: {str(e)}")
        return None

def send_whatsapp_message(to_number, message):
    try:
        message = twilio_client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_NUMBER')}",
            body=message,
            to=f"whatsapp:{to_number}"
        )
        return message.sid
    except Exception as e:
        print(f"Error sending WhatsApp message: {str(e)}")
        return None

@app.route("/webhook", methods=['POST'])
def webhook():
    # Verify request is from Twilio
    # Get incoming WhatsApp message details
    incoming_msg = request.values.get('Body', '')
    sender = request.values.get('From', '')
    num_media = int(request.values.get('NumMedia', 0))
    
    resp = MessagingResponse()
    
    if num_media > 0:
        # Handle image upload
        media_url = request.values.get('MediaUrl0', '')
        if sender not in user_states:
            user_states[sender] = {'state': 'awaiting_person'}
            
        if user_states[sender]['state'] == 'awaiting_person':
            # Save person image
            user_states[sender]['person_image'] = download_and_save_image(media_url)
            user_states[sender]['state'] = 'awaiting_garment'
            resp.message("Great! Now send me the garment image you'd like to try on.")
            
        elif user_states[sender]['state'] == 'awaiting_garment':
            # Save garment image and process
            garment_image = download_and_save_image(media_url)
            try:
                result_path = process_try_on(
                    user_states[sender]['person_image'],
                    garment_image
                )
                if result_path:
                    # Send result back to user
                    resp.message().media(result_path)
                else:
                    resp.message("Sorry, there was an error processing your images. Please try again.")
                # Clean up
                cleanup_images(user_states[sender]['person_image'], garment_image)
                user_states[sender]['state'] = 'awaiting_person'
            except Exception as e:
                print(f"Error in webhook: {str(e)}")
                resp.message("Sorry, something went wrong. Please try again.")
                
    else:
        # Handle text messages
        if incoming_msg.lower() == 'start':
            resp.message("Welcome to Virtual Try-On! Please send me a full-body photo of yourself.")
            user_states[sender] = {'state': 'awaiting_person'}
        else:
            resp.message("Please send an image or type 'start' to begin.")
    
    return str(resp)

def download_and_save_image(url):
    response = requests.get(url)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
    temp_file.write(response.content)
    return temp_file.name

def cleanup_images(*paths):
    for path in paths:
        try:
            os.remove(path)
        except:
            pass

@app.route("/", methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)