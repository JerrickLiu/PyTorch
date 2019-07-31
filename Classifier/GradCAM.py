import torch
from torch.autograd import Variable
from torch.autograd import Function
from torchvision import models
from torchvision import utils
import cv2
import sys
import numpy as np
import argparse
import os

image = []
i = 0

class FeatureExtractor():
    """ Class for extracting activations and
    registering gradients from targetted intermediate layers """

    def __init__(self, model, target_layers):
        self.model = model
        self.target_layers = target_layers
        self.gradients = []

    def save_gradient(self, grad):
        self.gradients.append(grad)

    def __call__(self, x):
        outputs = []
        self.gradients = []
        for name, module in self.model._modules.items():
            x = module(x)
            if name in self.target_layers:
                x.register_hook(self.save_gradient)
                outputs += [x]
        return outputs, x


class ModelOutputs():
    """ Class for making a forward pass, and getting:
	1. The network output.
	2. Activations from intermeddiate targetted layers.
	3. Gradients from intermeddiate targetted layers. """

    def __init__(self, model, target_layers):
        self.model = model
        if args.model == 'vgg19':
            self.feature_extractor = FeatureExtractor(self.model.features, target_layers)
        elif args.model == 'resnet50':
            self.feature_extractor = FeatureExtractor(self.model, target_layers)
        else:
            self.feature_extractor = FeatureExtractor(self.model,  target_layers)
    def get_gradients(self):
        return self.feature_extractor.gradients

    def __call__(self, x):
        target_activations, output = self.feature_extractor(x)
        output = output.view(output.size(0), -1)
        if args.model == 'vgg19':
            output = self.model.classifier(output)
        elif args.model == 'resnet50':
            output = resnet.fc(output)
        else:
            output = self.model.classifier(output)
        return target_activations, output


def preprocess_image(img):
    means = [0.485, 0.456, 0.406]
    stds = [0.229, 0.224, 0.225]

    preprocessed_img = img.copy()[:, :, ::-1]
    for i in range(3):
        preprocessed_img[:, :, i] = preprocessed_img[:, :, i] - means[i]
        preprocessed_img[:, :, i] = preprocessed_img[:, :, i] / stds[i]
    preprocessed_img = \
        np.ascontiguousarray(np.transpose(preprocessed_img, (2, 0, 1)))
    preprocessed_img = torch.from_numpy(preprocessed_img)
    preprocessed_img.unsqueeze_(0)
    input = Variable(preprocessed_img, requires_grad=True)
    return input


def show_cam_on_image(img, mask, name):
    heatmap = cv2.applyColorMap(np.uint8(255 * mask), cv2.COLORMAP_JET)
    heatmap = np.float32(heatmap) / 255
    cam = heatmap + np.float32(img)
    cam = cam / np.max(cam)
    cv2.imwrite("/Users/SirJerrick/Documents/results/cam{}.jpg".format(name), np.uint8(255 * cam))


class GradCam:
    def __init__(self, model, target_layer_names, use_cuda):
        self.model = model
        self.model.eval()
        self.cuda = use_cuda
        if self.cuda:
            self.model = model.cuda()

        self.extractor = ModelOutputs(self.model, target_layer_names)

    def forward(self, input):
        return self.model(input)

    def __call__(self, input, index=None):
        if self.cuda:
            features, output = self.extractor(input.cuda())
        else:
            features, output = self.extractor(input)

        if index == None:
            index = np.argmax(output.cpu().data.numpy())

        one_hot = np.zeros((1, output.size()[-1]), dtype=np.float32)
        one_hot[0][index] = 1
        one_hot = Variable(torch.from_numpy(one_hot), requires_grad=True)
        if self.cuda:
            one_hot = torch.sum(one_hot.cuda() * output)
        else:
            one_hot = torch.sum(one_hot * output)

        if args.model == 'vgg19':
            self.model.features.zero_grad()
            self.model.classifier.zero_grad()
        if args.model == 'resnet50':
            self.model.zero_grad()

        one_hot.backward(retain_graph=True)

        grads_val = self.extractor.get_gradients()[-1].cpu().data.numpy()

        target = features[-1]
        target = target.cpu().data.numpy()[0, :]

        weights = np.mean(grads_val, axis=(2, 3))[0, :]
        cam = np.zeros(target.shape[1:], dtype=np.float32)

        for i, w in enumerate(weights):
            cam += w * target[i, :, :]

        cam = np.maximum(cam, 0)
        cam = cv2.resize(cam, (224, 224))
        cam = cam - np.min(cam)
        cam = cam / np.max(cam)
        return cam

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--use-cuda', action='store_true', default=False,
                        help='Use NVIDIA GPU acceleration')
    parser.add_argument('--image-path', type=str, default='/Users/SirJerrick/Downloads/images/',
                        help='Input image path')
    parser.add_argument('--model', type=str, default = 'densenet121')

    args = parser.parse_args()
    args.use_cuda = args.use_cuda and torch.cuda.is_available()
    if args.use_cuda:
        print("Using GPU for acceleration")
    else:
        print("Using CPU for computation")

    return args


if __name__ == '__main__':
    """ python grad_cam.py <path_to_image>
	1. Loads an image with opencv.
	2. Preprocesses it for VGG19 and converts to a pytorch variable.
	3. Makes a forward pass to find the category index with the highest score,
	and computes intermediate activations.
	Makes the visualization. """

    args = get_args()

    # Can work with any model, but it assumes that the model has a
    # feature method, and a classifier method,
    # as in the VGG models in torchvision.
    saved_model = False

    if not saved_model:

        if args.model == 'vgg19':
            model = models.vgg19(pretrained = True)
        elif args.model == 'resnet50':
            resnet = models.resnet50(pretrained=True)
            model = models.resnet50(pretrained=True)
        elif args.model == 'densenet121':
            model =models.densenet121(pretrained=True)
        else:
            print('Unavailable model, please choose from vgg19, resnet50, or densenet121')

    if args.use_cuda:
        model.cuda()

    if args.model == 'vgg19':
        grad_cam = GradCam(model=model,
                       target_layer_names=["35"], use_cuda=args.use_cuda)

    if args.model == 'resnet50':
        del model.fc
        grad_cam = GradCam(model = model,
                           target_layer_names=['layer4'], use_cuda=args.use_cuda)

    if args.model == 'densenet121':
        grad_cam = GradCam(model = model, target_layer_names=['denselayer16'], use_cuda=args.use_cuda)

    x = os.walk(args.image_path)

    for root, dirs, filename in x:
        # print(type(grad_cam))
        print(filename)

        for s in filename:
            image.append(cv2.imread(args.image_path + s, 1))

        for img in image:
            img = np.float32(cv2.resize(img, (224, 224))) / 255
            input = preprocess_image(img)
            print('Creating heatmap')
            # If None, returns the map for the highest scoring category.
            # Otherwise, targets the requested index.
            target_index = None

            mask = grad_cam(input, target_index)

            i +=1

            show_cam_on_image(img, mask, i)
