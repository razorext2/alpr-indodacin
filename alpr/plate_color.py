from flask import Blueprint, request, Flask, jsonify
from flask_mysqldb import MySQLdb, MySQL
import cv2 as cv
import numpy as np
from datetime import datetime
import os

plate_color = Blueprint('plate_color', __name__)

app = Flask(__name__)

app.secret_key = "plate_color"

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'flaskdb'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# Initialize the parameters
confThreshold = 0.7   # Confidence threshold
nmsThreshold = 0.4    # Non-maximum suppression threshold

inpWidth = 416  # Width of network's input image
inpHeight = 416  # Height of network's input image

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

# Get the names of the output layers
def getOutputsNames(net):
    # Get the names of all the layers in the network
    layersNames = net.getLayerNames()
    # Get the names of the output layers, i.e. the layers with unconnected outputs
    return [layersNames[i[0] - 1] for i in net.getUnconnectedOutLayers()]

# Draw the predicted bounding box and recognize the plate color
def drawPred(frame, classId, conf, left, top, right, bottom, token):
    # Create directory structure if it does not exist
    dirname = 'static/storage/' + token
    full_dirname = dirname + '/full'
    os.makedirs(full_dirname, exist_ok=True)
    
    # Save the full frame before cropping
    filename = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    full_image_path = full_dirname + '/' + filename + '-full.jpg'
    cv.imwrite(full_image_path, frame)

    # Crop the detected plate
    plate = frame[top:bottom, left:right]
    
    # Save the cropped plate
    cropped_filename = dirname + '/' + filename + '.jpg'
    cv.imwrite(cropped_filename, plate)

    # Recognize the color of the plate
    average_color_per_row = np.average(plate, axis=0)
    average_color = np.average(average_color_per_row, axis=0)
    color = np.uint8(average_color).tolist()

    # Convert the color to a string
    plate_color = 'rgb({},{},{})'.format(color[0], color[1], color[2])

    # Save the plate color to the database
    curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    curl.execute("SELECT id FROM apps WHERE token=%s", (token,))
    token_id = curl.fetchone()
    insert = curl.execute("INSERT INTO plate_color (app_id, plate_color, file, before_crop) VALUES (%s,%s,%s,%s)", (token_id['id'], plate_color, cropped_filename, full_image_path))
    mysql.connection.commit()

    return plate_color

# Remove the bounding boxes with low confidence using non-maxima suppression
def postprocess(frame, outs, token):
    frameHeight = frame.shape[0]
    frameWidth = frame.shape[1]

    classIds = []
    confidences = []
    boxes = []
    # Scan through all the bounding boxes output from the network and keep only the
    # ones with high confidence scores. Assign the box's class label as the class with the highest score.
    for out in outs:
        print("out.shape : ", out.shape)
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

    # Perform non-maximum suppression to eliminate redundant overlapping boxes with
    # lower confidences.
    indices = cv.dnn.NMSBoxes(boxes, confidences, confThreshold, nmsThreshold)
    print(len(confidences))
    plate_color = ''
    for i in indices:
        i = i[0]
        box = boxes[i]
        left = box[0]
        top = box[1]
        width = box[2]
        height = box[3]
        plate_color = drawPred(frame, classIds[i], confidences[i], left, top, left + width, top + height, token)
    if plate_color:
        return [len(confidences), plate_color]
    else:
        return [len(confidences)]

@plate_color.route("/app/<token>", methods=["GET", "POST"])
def app(token):
    if request.method == 'POST':
        curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        curl.execute("SELECT * FROM apps WHERE token=%s", (token,))
        app = curl.fetchone()
        if not app:
            value = {
                'status':0,
                'message':'Token is Invalid',
            }
            return value

        # Get Image Request
        imagefile = request.files['imageFile'].read()

        # Convert string data to numpy array
        npimg = np.fromstring(imagefile, dtype=np.uint8)

        # Convert numpy array to image
        img = cv.imdecode(npimg, cv.IMREAD_UNCHANGED)

        blob = cv.dnn.blobFromImage(img, 1/255, (inpWidth, inpHeight), [0,0,0], 1, crop=False)

        # Sets the input to the network
        net.setInput(blob)

        # Runs the forward pass to get output of the output layers
        outs = net.forward(getOutputsNames(net))

        # Remove the bounding boxes with low confidence
        test = postprocess(img, outs, token)
   
        if test[0] == 0:
            value = {
                'status':0,
                'message':'Plat Nomor Tidak Terdeteksi',
            }
            return value

        if len(test) >= 2:
            value = {
                'status':1,
                'message':'Plat Nomor Terdeteksi',
                'plate_color': test[1]
            }
            return value

        elif len(test) == 1:
            value = {
                'status':1,
                'message':'Plat Nomor Terdeteksi',
                'plate_color': 'Gagal Membaca Warna Plat Nomor'
            }
            return value
    else:
        curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        curl.execute("SELECT * FROM apps WHERE token=%s", (token,))
        app = curl.fetchone()
        if not app:
            value = {
                'status':0,
                'message':'Token is Invalid',
            }
            return value

        curl.execute("SELECT * FROM plate_color WHERE app_id=%s", (app['id'],))
        data = curl.fetchall()
        return jsonify(data)
