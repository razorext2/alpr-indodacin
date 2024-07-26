from flask import Blueprint, request, Flask, jsonify
from flask_mysqldb import MySQLdb, MySQL
import cv2 as cv
import numpy as np
import pytesseract
from datetime import datetime
import os

alpr = Blueprint('alpr', __name__)

app = Flask(__name__)

app.secret_key = "alpr"

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'flaskdb'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# Initialize the parameters
confThreshold = 0.1   # Confidence threshold
nmsThreshold = 0.45   # Non-maximum suppression threshold

# Initialize the pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

inpWidth = 608 # Width of network's input image
inpHeight = 608 # Height of network's input image

# Load names of classes
classesFile = "alpr/classes.names"

classes = None
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')

# Give the configuration and weight files for the model and load the network using them.
modelConfiguration = "alpr/darknet-yolov3.cfg"
modelWeights = "alpr/lapi.weights"
net = cv.dnn.readNetFromDarknet(modelConfiguration, modelWeights)
net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)

def getOutputsNames(net):
    """
    Get the names of the output layers.
    """
    layersNames = net.getLayerNames()
    return [layersNames[i[0] - 1] for i in net.getUnconnectedOutLayers()]

def preprocess_image(img):
    """
    Preprocess the image for better detection.
    """
    scale_factor = 1.5
    width = int(img.shape[1] * scale_factor)
    height = int(img.shape[0] * scale_factor)
    dim = (width, height)
    resized_img = cv.resize(img, dim, interpolation=cv.INTER_LINEAR)

    top, bottom, left, right = (0, 0, 0, 0)
    if width > height:
        pad = width - height
        top = pad // 2
        bottom = pad - top
    else:
        pad = height - width
        left = pad // 2
        right = pad - left

    padded_img = cv.copyMakeBorder(resized_img, top, bottom, left, right, cv.BORDER_CONSTANT, value=[0, 0, 0])
    return padded_img

def drawPred(frame, classId, conf, left, top, right, bottom, token):
    """
    Draw the predicted bounding box and process the detected plate.
    """
    dirname = f'static/storage/{token}'
    full_dirname = f'{dirname}/full'
    os.makedirs(full_dirname, exist_ok=True)
    
    filename = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    full_image_path = f'{full_dirname}/{filename}-full.jpg'
    cv.imwrite(full_image_path, frame)

    plate = frame[top:bottom, left:right]
    cropped_filename = f'{dirname}/{filename}.jpg'
    cv.imwrite(cropped_filename, plate)

    gray = cv.cvtColor(plate, cv.COLOR_BGR2GRAY)
    blur = cv.GaussianBlur(gray, (5, 5), 0)
    thresh = cv.threshold(blur, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)[1]

    cv.imwrite(f'{dirname}/{filename}-gray.jpg', gray)
    cv.imwrite(f'{dirname}/{filename}-thresh.jpg', thresh)

    text = pytesseract.image_to_string(thresh, config="--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    print("Detected license plate Number:", text)
    
    s = ''.join(ch for ch in text if ch.isalnum())

    with mysql.connection.cursor(MySQLdb.cursors.DictCursor) as curl:
        curl.execute("SELECT id FROM apps WHERE token=%s", (token,))
        token_id = curl.fetchone()
        curl.execute("INSERT INTO license_plate (app_id, plate_number, file, before_crop) VALUES (%s,%s,%s,%s)",
                     (token_id['id'], s, cropped_filename, full_image_path))
        mysql.connection.commit()

    return s

def postprocess(frame, outs, token):
    """
    Remove the bounding boxes with low confidence using non-maxima suppression.
    """
    frameHeight = frame.shape[0]
    frameWidth = frame.shape[1]

    classIds = []
    confidences = []
    boxes = []

    for out in outs:
        for detection in out:
            scores = detection[5:]
            classId = np.argmax(scores)
            confidence = scores[classId]
            if confidence > confThreshold:
                center_x = int(detection[0] * frameWidth)
                center_y = int(detection[1] * frameHeight)
                width = int(detection[2] * frameWidth)
                height = int(detection[3] * frameHeight)
                left = int(center_x - width / 2)
                top = int(center_y - height / 2)
                classIds.append(classId)
                confidences.append(float(confidence))
                boxes.append([left, top, width, height])

    indices = cv.dnn.NMSBoxes(boxes, confidences, confThreshold, nmsThreshold)
    license = ''
    for i in indices:
        i = i[0]
        box = boxes[i]
        left = box[0]
        top = box[1]
        width = box[2]
        height = box[3]
        license = drawPred(frame, classIds[i], confidences[i], left, top, left + width, top + height, token)
    return [len(confidences), license] if license else [len(confidences)]

@alpr.route("/app/<token>", methods=["GET", "POST"])
def app(token):
    if request.method == 'POST':
        with mysql.connection.cursor(MySQLdb.cursors.DictCursor) as curl:
            curl.execute("SELECT * FROM apps WHERE token=%s", (token,))
            app = curl.fetchone()
            if not app:
                return jsonify({'status': 0, 'message': 'Token is Invalid'})

            imagefile = request.files['imageFile'].read()
            npimg = np.fromstring(imagefile, dtype=np.uint8)
            img = cv.imdecode(npimg, cv.IMREAD_UNCHANGED)

            # Convert RGBA to RGB if necessary
            if img.shape[2] == 4:
                img = cv.cvtColor(img, cv.COLOR_BGRA2BGR)

            img = preprocess_image(img)  # Preprocess image for better detection
            blob = cv.dnn.blobFromImage(img, 1/255, (inpWidth, inpHeight), [0,0,0], 1, crop=False)
            net.setInput(blob)
            outs = net.forward(getOutputsNames(net))

            test = postprocess(img, outs, token)
            if test[0] == 0:
                return jsonify({'status': 0, 'message': 'Plat Nomor Tidak Terdeteksi'})
            if len(test) >= 2:
                return jsonify({'status': 1, 'message': 'Plat Nomor Terdeteksi', 'license': test[1]})
            elif len(test) == 1:
                return jsonify({'status': 1, 'message': 'Plat Nomor Terdeteksi', 'license': 'Gagal Membaca Plat Nomor'})
    else:
        with mysql.connection.cursor(MySQLdb.cursors.DictCursor) as curl:
            curl.execute("SELECT * FROM apps WHERE token=%s", (token,))
            app = curl.fetchone()
            if not app:
                return jsonify({'status': 0, 'message': 'Token is Invalid'})

            curl.execute("SELECT * FROM license_plate WHERE app_id=%s", (app['id'],))
            data = curl.fetchall()
            return jsonify(data)

if __name__ == "__main__":
    app.run(debug=True)
