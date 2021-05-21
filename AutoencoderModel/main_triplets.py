
from tensorflow.keras import backend as K
import random
import numpy as np
from keras.layers import *
from keras.models import Model
import os
from image_loading import *
import argparse
from transform import *
from triplets import *
from autoencoder import TripletsEncoder
from scipy import spatial
from sklearn.neighbors import NearestNeighbors
from image_loading import Loader
from autoencoder import AutoEncoder
from transform import normalize_img, data_augmentation
from final_display import *
from visualization import *
from request import submit
import argparse
import wandb


output_shape_model = (100)
input_shape_model = (324, 324, 3)


parser = argparse.ArgumentParser(description='Challenge presentation example')
parser.add_argument('--data_path',
                    '-d',
                    type=str,
                    default='dataset',
                    help='Dataset path')
parser.add_argument('-mode',
                    type=str,
                    default='training model',
                    help='training or test')
parser.add_argument('-n',
                    type=str,
                    default='training')
parser.add_argument('-lr',
                    type=float,
                    default=1e-4,
                    help='learning rate')
parser.add_argument('-e',
                    type=int,
                    default=50,
                    help='number of epochs')
parser.add_argument('-bs',
                    type=int,
                    default=32,
                    help='batch size')
parser.add_argument('-loss',
                    type=str,
                    default="mse",
                    help='loss function')
parser.add_argument('-wandb',
                    type=str,
                    default='True',
                    help='Log on WandB (default = True)')
parser.add_argument('-img_size',
                    type=int,
                    default=324,
                    help='image size for the model')
parser.add_argument('-channels',
                    type=int,
                    default=3,
                    help='number of channels')
parser.add_argument('-metric',
                    type=str,
                    default='minkowski',
                    help='metric to compute distance query-gallery')
args = parser.parse_args()



TrainDir = os.path.join(os.getcwd(), args.data_path, "training")
QueryDir = os.path.join(os.getcwd(), args.data_path, "validation", "query")
GalleryDir = os.path.join(os.getcwd(), args.data_path, "validation", "gallery")
OutputDir = os.path.join(os.getcwd(), "output", "triplets_loss")
if not os.path.exists(OutputDir):
    os.makedirs(OutputDir)

# Build models
tripletsFile = os.path.join(OutputDir, "triplets_encoder.h5")



print('loading_images')
# create loader
loader = Loader(args.img_size, args.img_size, args.channels)

# extract img final for the model
shape_img = (args.img_size, args.img_size, args.channels)  # bc we need it as argument for the Autoencoder()
print("Image size", shape_img)

triplet_model = TripletsEncoder(shape_img, tripletsFile)
triplet_model.set_arch()

if args.mode == "training model":
    print('start_training')
    # TRAIN
    # Read images
    train_map = loader.get_files(TrainDir)
    train_names, train_paths, imgs_train, train_classes = loader.get_data_paths(train_map)

    # Normalize all images
    print("\nNormalizing training images")
    imgs_train = normalize_img(imgs_train)

    # Convert images to numpy array of right dimensions
    print("\nConverting to numpy array of right dimensions")
    X_train = np.array(imgs_train).reshape((-1,) + (324, 324, 3))
    print(">>> X_train.shape = " + str(X_train.shape))



    print('compile')
    triplet_model.compile_triplets(triplet_loss, optimizer='adam')

    print('fitting')
    triplet_model.fit_triplets(data_generator(train_classes,X_train, 64), steps_per_epoch=1, epochs = 3)

    print('saving')
    triplet_model.save_triplets()


    print("\nCreating embeddings")
    E_train = triplet_model.predict_triplets(X_train)
    print(E_train.shape)
    E_train_flatten = E_train.reshape((-1, np.prod(output_shape_model)))
    print(">>> E_train.shape = " + str(E_train.shape))
    print(">>> E_train_flatten.shape = " + str(E_train_flatten.shape))

# Read images
query_map = loader.get_files(QueryDir)
query_names, query_paths, imgs_query, query_classes = loader.get_data_paths(query_map)
gallery_map = loader.get_files(GalleryDir)
gallery_names, gallery_paths, imgs_gallery, gallery_classes = loader.get_data_paths(gallery_map)

# Normalize all images
print("Normalizing query images")
imgs_query = normalize_img(imgs_query)
print("Normalizing gallery images")
imgs_gallery = normalize_img(imgs_gallery)

# Convert images to numpy array of right dimensions
print("\nConverting to numpy array of right dimensions")
X_query = np.array(imgs_query).reshape((-1,) + input_shape_model)
X_gallery = np.array(imgs_gallery).reshape((-1,) + input_shape_model)
print(">>> X_query.shape = " + str(X_query.shape))
print(">>> X_gallery.shape = " + str(X_gallery.shape))

if args.mode != "training model":
    print("\nLoading model...")
    triplet_model.load_triplets(triplet_loss, optimizer="adam")

# Create embeddings using model
print("\nCreating embeddings")
E_query = triplet_model.predict_triplets(X_query)
E_query_flatten = E_query.reshape((-1, np.prod(output_shape_model)))
E_gallery = triplet_model.predict_triplets(X_gallery)
E_gallery_flatten = E_gallery.reshape((-1, np.prod(output_shape_model)))
print(">>> E_query.shape = " + str(E_query.shape))
print(">>> E_gallery.shape = " + str(E_gallery.shape))
print(">>> E_query_flatten.shape = " + str(E_query_flatten.shape))
print(">>> E_gallery_flatten.shape = " + str(E_gallery_flatten.shape))

# define the distance between query - gallery features vectors
pairwise_dist = spatial.distance.cdist(E_query_flatten, E_gallery_flatten, args.metric, p=2.)
# rows -> queries | columns -> gallery --> cell = distance between query-gallery image
print('\nComputed distances and got c-dist {}'.format(pairwise_dist.shape))

print("\nCalculating indices...")
indices = np.argsort(pairwise_dist, axis=-1)
print("Indices: {}".format(indices))


print("\nGallery classes", gallery_classes)
gallery_matches = gallery_classes[indices]
print("\nMatches")
print(gallery_matches)


def topk_accuracy(gt_label, matched_label, k=1):
    matched_label = matched_label[:, :k]
    total = matched_label.shape[0]
    correct = 0
    for q_idx, q_lbl in enumerate(gt_label):
        correct += np.any(q_lbl == matched_label[q_idx, :]).item()
    acc_tmp = correct / total

    return acc_tmp


print('\n########## RESULTS ##########')

for k in [1, 3, 10]:
    topk_acc = topk_accuracy(query_classes, gallery_matches, k)
    print('>>> Top-{:d} Accuracy: {:.3f}'.format(k, topk_acc))

# Fit kNN model on training images
print("\nFitting KNN model on training data...")
k = 10
knn = NearestNeighbors(n_neighbors=k, metric="cosine")
knn.fit(E_gallery_flatten)
print("Done fitting")

# Querying on test images
final_res = dict()
print("\nQuerying...")
for i, emb_flatten in enumerate(E_query_flatten):
    distances, indx = knn.kneighbors([emb_flatten])
    # print("\nFor query image_" + str(i))
    # print(">> Indices:" + str(indx))
    # print(">> Distances:" + str(distances))
    img_query = imgs_query[i]  # query image
    query_name = query_names[i]
    imgs_retrieval = [imgs_gallery[idx] for idx in indx.flatten()]
    names_retrieval = [gallery_names[idx] for idx in indx.flatten()]
    # outFile = os.path.join(OutputDir, "ConvAE_retrieval_" + str(i) + ".png")
    plot_query_retrieval(img_query, imgs_retrieval, None)
    create_results_dict(final_res, query_name, names_retrieval)


print("\nDone querying, saving results...")
final_results = create_final_dict(final_res)
url = "http://kamino.disi.unitn.it:3001/results/"
# submit(final_results, url)
print("Results saved")


