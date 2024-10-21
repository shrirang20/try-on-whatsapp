from flask import Flask, request, jsonify
import os
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import gradio_client
import tempfile
from PIL import Image
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
import json

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
        print("Initializing Gradio client...")
        client = gradio_client.Client("Nymbo/Virtual-Try-On")
        print("Gradio client initialized")

        # Open and verify both images exist
        if not (os.path.exists(person_image_path) and os.path.exists(garment_image_path)):
            print("One or both image paths don't exist")
            print(f"Person image path exists: {os.path.exists(person_image_path)}")
            print(f"Garment image path exists: {os.path.exists(garment_image_path)}")
            return None

        print("Setting up input parameters...")
        # Create the input dictionary exactly as shown in API docs
        input_dict = {
            "background": None,
            "layers": [],
            "composite": None
        }

        print(f"Person image path: {person_image_path}")
        print(f"Garment image path: {garment_image_path}")

        print("Making prediction...")
        # First try getting available API endpoints
        endpoints = client.endpoints
        print(f"Available endpoints: {endpoints}")

        try:
            # Try with the documented endpoint first
            result = client.predict(
                str(person_image_path),    # Send path as string
                str(garment_image_path),   # Send path as string
                "Virtual Try-on",          # Description
                True,                      # is_checked
                False,                     # is_checked_crop
                30,                        # denoise_steps
                42,                        # seed
                api_name="/tryon"        # Try the default predict endpoint
            )
            print("Prediction completed successfully")
            
            if isinstance(result, tuple) and len(result) > 0:
                print(f"Result type: {type(result)}")
                print(f"Result length: {len(result)}")
                return result[0]
            return result

        except Exception as e:
            print(f"First attempt failed: {str(e)}")
            # Try with simplified parameters
            result = client.predict(
                person_image_path,         # Direct file path
                garment_image_path,        # Direct file path
                api_name="/tryon"        # Try the default predict endpoint
            )
            
            if isinstance(result, tuple) and len(result) > 0:
                return result[0]
            return result

    except Exception as e:
        print(f"Error in process_try_on: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        
        # Try to print file contents/stats for debugging
        try:
            print(f"Person image size: {os.path.getsize(person_image_path)}")
            print(f"Garment image size: {os.path.getsize(garment_image_path)}")
        except Exception as file_e:
            print(f"Error checking files: {str(file_e)}")
            
        return None

def get_media_content_url(media_url):
    try:
        # Strip .json from the URL if it exists
        base_url = media_url.replace('.json', '')
        # Add /content to get the actual media content
        content_url = f"{base_url}/content"
        return content_url
    except Exception as e:
        print(f"Error constructing media content URL: {str(e)}")
        return None

def download_and_save_image(message_sid, media_sid):
    try:
        print(f"Downloading media - Message SID: {message_sid}, Media SID: {media_sid}")
        
        # Create temp file with .jpg extension
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        
        # Get the media using Twilio client
        media = twilio_client.messages(message_sid).media(media_sid).fetch()
        
        # Construct the direct media URL
        media_url = f"https://api.twilio.com{media.uri.replace('.json', '')}"
        print(f"Constructed media URL: {media_url}")
        
        # Download the image with authentication
        response = requests.get(
            media_url,
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            headers={'Accept': 'image/jpeg'}
        )
        response.raise_for_status()
        
        # Write content to file
        temp_file.write(response.content)
        temp_file.close()
        
        # Verify and potentially convert image
        with Image.open(temp_file.name) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # Save as JPEG
            img.save(temp_file.name, 'JPEG')
            
        try:
            print(f"Saved image size: {os.path.getsize(temp_file.name)} bytes")
            with Image.open(temp_file.name) as img:
                print(f"Image dimensions: {img.size}")
                print(f"Image mode: {img.mode}")
        except Exception as e:
            print(f"Error checking saved image: {str(e)}")
        return temp_file.name
    
    except Exception as e:
        print(f"Error downloading/saving image: {str(e)}")
        if 'response' in locals():
            print(f"Response status code: {response.status_code}")
            print(f"Response headers: {response.headers}")
            try:
                print(f"Response content: {response.content[:200]}...")
            except:
                pass
        return None

@app.route('/health')
def healthcheck():
    return jsonify({
        "status": "healthy",
        "message": "Virtual Try-On Bot is running!"
    })

@app.route("/webhook", methods=['POST'])
def webhook():
    try:
        # Get incoming WhatsApp message details
        incoming_msg = request.values.get('Body', '').lower()
        sender = request.values.get('From', '')
        num_media = int(request.values.get('NumMedia', 0))
        message_sid = request.values.get('MessageSid', '')
        
        print(f"Received message from {sender}")
        print(f"Message SID: {message_sid}")
        print(f"Message content: {incoming_msg}")
        print(f"Number of media: {num_media}")
        
        resp = MessagingResponse()
        
        # Initialize user state if not exists
        if sender not in user_states:
            user_states[sender] = {'state': None}
        
        # Handle text commands
        if num_media == 0:
            if incoming_msg == 'start':
                user_states[sender] = {'state': 'awaiting_person'}
                resp.message("Welcome to Virtual Try-On! Please send me a full-body photo of yourself.")
            elif incoming_msg == 'reset':
                user_states[sender] = {'state': 'awaiting_person'}
                resp.message("Session reset. Please send a full-body photo to start again.")
            else:
                resp.message("Please send 'start' to begin or 'reset' to start over.")
            return str(resp)
        
        # Handle image uploads
        if num_media > 0:
            # Get media SID from the URL
            media_url = request.values.get('MediaUrl0', '')
            media_sid = media_url.split('/')[-1]
            
            print(f"Media SID: {media_sid}")
            
            image_path = download_and_save_image(message_sid, media_sid)
            
            if not image_path:
                resp.message("Sorry, I couldn't download that image. Please try again.")
                return str(resp)
            
            current_state = user_states[sender].get('state')
            
            if current_state == 'awaiting_person':
                user_states[sender]['person_image'] = image_path
                user_states[sender]['state'] = 'awaiting_garment'
                resp.message("Great! Now send me the garment image you'd like to try on.")
                
            elif current_state == 'awaiting_garment':
                person_image = user_states[sender].get('person_image')
                if not person_image:
                    resp.message("Sorry, I lost track of your person image. Please type 'start' to begin again.")
                    return str(resp)
                
                # Process the virtual try-on
                result_path = process_try_on(person_image, image_path)
                
                if result_path:
                    # Send result back via WhatsApp
                    msg = resp.message("Here's your virtual try-on result!")
                    msg.media(result_path)
                else:
                    msg = resp.message("Sorry, there was an error processing your images. Please type 'start' to try again.")
                
                # Clean up
                cleanup_images(person_image, image_path)
                user_states[sender] = {'state': 'awaiting_person'}
            
            else:
                resp.message("Please type 'start' to begin the virtual try-on process.")
                cleanup_images(image_path)
        
        return str(resp)
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500

def cleanup_images(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error cleaning up {path}: {str(e)}")

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)