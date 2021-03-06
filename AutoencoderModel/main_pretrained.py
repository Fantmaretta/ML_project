import os
import numpy as np
import tensorflow as tf
from sklearn.neighbors import NearestNeighbors
from visualization import plot_query_retrieval
from image_loading import Loader
from transform import normalize_img
from final_display import *
from scipy import spatial
import argparse
import wandb


parser = argparse.ArgumentParser(description='Challenge presentation example')

parser.add_argument('--data_path',
                    '-d',
                    type=str,
                    default='dataset',
                    help='Dataset path')
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
                    default='False',
                    help='Log on WandB (default = False)')
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
parser.add_argument('-plot',
                    type=str,
                    default='False',
                    help='Helper to visualize the results (default = False)')
args = parser.parse_args()

if args.wandb == 'True':
    # Login to wandb
    wandb.login(key='f97918185ed02886a90fa4464e7469c13c017460')
    # Save results online
    os.environ['WANDB_MODE'] = 'dryrun'
    # Start a W&B run
    wandb.init(project='aml-challenge',)
    wandb.config.epochs = args.e
    wandb.config.batch_size = args.bs

# Make paths
TrainDir = os.path.join(os.getcwd(), args.data_path, "training")
QueryDir = os.path.join(os.getcwd(), args.data_path, "validation", "query")
GalleryDir = os.path.join(os.getcwd(), args.data_path, "validation", "gallery")
OutputDir = os.path.join(os.getcwd(), "output", "pretrained")
if not os.path.exists(OutputDir):
    os.makedirs(OutputDir)

# Create loader
loader = Loader(args.img_size, args.img_size, args.channels)

# Extract img final for the model
shape_img = (args.img_size, args.img_size, args.channels)
print("Image size", shape_img)

# Read images
query_map = loader.get_files(QueryDir)
query_names, query_paths, imgs_query, query_classes = loader.get_data_paths(query_map)
gallery_map = loader.get_files(GalleryDir)
gallery_names, gallery_paths, imgs_gallery, gallery_classes = loader.get_data_paths(gallery_map)

# Load pre-trained ResNet50 model + higher level layers
print("\nLoading model...")
model = tf.keras.applications.ResNet50(weights='imagenet', include_top=False, input_shape=shape_img)
model.summary()

shape_img_resize = tuple([int(x) for x in model.input.shape[1:]])
input_shape_model = tuple([int(x) for x in model.input.shape[1:]])
output_shape_model = tuple([int(x) for x in model.output.shape[1:]])

# Normalize all images
print("Normalizing query images")
imgs_query = normalize_img(imgs_query)
print("Normalizing gallery images")
imgs_gallery = normalize_img(imgs_gallery)

# Convert images to numpy array of right dimensions
print("\nConverting to numpy array of right dimensions")
X_query = np.array(imgs_query).reshape((-1,) + input_shape_model)
X_gallery = np.array(imgs_gallery).reshape((-1,) + input_shape_model)

# Create embeddings using model
print("\nCreating embeddings")
E_query = model.predict(X_query)
E_query_flatten = E_query.reshape((-1, np.prod(output_shape_model)))
E_gallery = model.predict(X_gallery)
E_gallery_flatten = E_gallery.reshape((-1, np.prod(output_shape_model)))



# Compute top-k
def topk_accuracy(gt_label, matched_label, k=1):
    matched_label = matched_label[:, :k]
    total = matched_label.shape[0]
    correct = 0
    for q_idx, q_lbl in enumerate(gt_label):
        correct += np.any(q_lbl == matched_label[q_idx, :]).item()
    acc_tmp = correct/total
    return acc_tmp


# Distancces between query and gallery with pairwise distance

print("\nComputing pairwise distance between query and gallery images")

# Define the distance between query - gallery features vectors
pairwise_dist = spatial.distance.cdist(E_query_flatten, E_gallery_flatten, args.metric, p=2.)
print('\nComputed distances and got c-dist {}'.format(pairwise_dist.shape))

print("\nCalculating indices and gallery matches...")
indices = np.argsort(pairwise_dist, axis=-1)
gallery_matches = gallery_classes[indices]

final_res_pairwise = dict()
for i, emb_flatten in enumerate(indices):
    img_query = imgs_query[i]
    query_name = query_names[i]
    imgs_retrieval = [imgs_gallery[indx] for indx in indices[i][:10]]
    names_retrieval = [gallery_names[indx] for indx in indices[i][:10]]

    if args.plot == 'True':
        outFile = os.path.join(OutputDir, "ConvAE_retrieval_" + str(i) + ".png")
        plot_query_retrieval(img_query, imgs_retrieval, None)

    create_results_dict(final_res_pairwise, query_name, names_retrieval)

print('\nRESULTS pairwise:')
for k in [1, 3, 10]:
    topk_acc = topk_accuracy(query_classes, gallery_matches, k)
    print('>>> Top-{:d} Accuracy with pairwise distance: {:.3f}'.format(k, topk_acc))



# Distances between query and gallery with knn distance

print("\nComputing knn for distance between query and gallery images")

# Fit kNN model on gallery images
print("\nFitting KNN model on training data...")
k = 10
knn = NearestNeighbors(n_neighbors=k, metric="cosine")
knn.fit(E_gallery_flatten)
print("Done fitting")

# Querying on test images
final_res_knn = dict()
print("\nQuerying...")
query_classes_knn = []
class_retrieval_knn = []
for i, emb_flatten in enumerate(E_query_flatten):
    distances, indx = knn.kneighbors([emb_flatten])
    img_query = imgs_query[i]
    query_name = query_names[i]
    query_classes_knn.append(query_classes[i])
    imgs_retrieval = [imgs_gallery[idx] for idx in indx.flatten()]
    names_retrieval = [gallery_names[idx] for idx in indx.flatten()]
    class_retrieval_knn.append([gallery_classes[idx] for idx in indx.flatten()])

    if args.plot == 'True':
        outFile = os.path.join(OutputDir, "ConvAE_retrieval_knn_" + str(i) + ".png")
        plot_query_retrieval(img_query, imgs_retrieval, None)

    create_results_dict(final_res_knn, query_name, names_retrieval)

print('\nRESULTS knn:')
for k in [1, 3, 10]:
    topk_acc = topk_accuracy(np.array(query_classes_knn), np.array(class_retrieval_knn), k)
    print('>>> Top-{:d} Accuracy with knn: {:.3f}'.format(k, topk_acc))

print('Saving results...')
final_results_pairwise = create_final_dict(final_res_pairwise)
final_results_knn = create_final_dict(final_res_knn)
url = "http://ec2-18-191-24-254.us-east-2.compute.amazonaws.com/results/"
#submit(final_results_pairwise, url)
submit(final_results_knn, url)
print("Done saving")


