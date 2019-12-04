import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from .Model import Model
# import tools.DataVis as DataVis
# from tools.PointCloudDataset import save_objs
from vae.tools import Ops
# from tools.plotter import Plotter
# from tools.sfc import SFC

class PointCloudEncoder(nn.Module):

	def __init__(self, size, dim, batch_size=64, enc_size=100, kernel_size=16,
			init_channels=16):
		super(PointCloudEncoder, self).__init__()
		self.size = size
		self.dim = dim
		self.batch_size = batch_size
		self.kernel_size = kernel_size
		self.enc_size =  enc_size
		self.init_channels = init_channels

		conv_enc = nn.Sequential()

		current_size = self.size
		in_channels = self.dim
		out_channels = self.init_channels
		layer_num = 1
		padding = (self.kernel_size - 1)//2
		while current_size > 16:
			conv_enc.add_module('conv{}'.format(layer_num),
					nn.Conv1d(in_channels, out_channels, self.kernel_size,
						stride=2,
						padding=padding))
			conv_enc.add_module('bn{}'.format(layer_num),
					nn.BatchNorm1d(out_channels))
			conv_enc.add_module('lrelu{}'.format(layer_num),
					nn.LeakyReLU(0.2, inplace=True))

			current_size = current_size //2
			in_channels = out_channels
			out_channels = out_channels * 2
			layer_num = layer_num + 1

		self.conv_enc = conv_enc

		self.fc = nn.Linear(16*in_channels, self.enc_size)

	def forward(self, x):
		t = self.conv_enc(x).view(self.batch_size, -1)
		out = self.fc(t)

		return out


class PointCloudDecoder(nn.Module):

	def __init__(self, size, dim, batch_size=64, enc_size=100, kernel_size=16,
			init_channels=1024):
		super(PointCloudDecoder, self).__init__()
		self.size = size
		self.dim = dim
		self.batch_size = batch_size
		self.kernel_size = kernel_size
		self.enc_size =  enc_size
		self.init_channels = init_channels

		self.fc = nn.Linear(self.enc_size, 16*self.init_channels)

		conv_dec = nn.Sequential()

		current_size = 16*2
		in_channels = self.init_channels
		out_channels = in_channels//2
		layer_num = 1
		padding = (self.kernel_size - 1)//2
		while current_size < self.size:
			conv_dec.add_module('conv{}'.format(layer_num),
					nn.ConvTranspose1d(in_channels, out_channels, self.kernel_size,
						stride=2,
						padding=padding))
			conv_dec.add_module('bn{}'.format(layer_num),
					nn.BatchNorm1d(out_channels))
			conv_dec.add_module('lrelu{}'.format(layer_num),
					nn.LeakyReLU(0.2, inplace=True))

			current_size = current_size * 2
			in_channels = out_channels
			out_channels = out_channels // 2
			layer_num = layer_num + 1

		conv_last = nn.Sequential()
		conv_last.add_module('conv{}'.format(layer_num),
				nn.ConvTranspose1d(in_channels, self.dim, self.kernel_size,
					stride=2,
					padding=padding))
		conv_last.add_module('lrelu{}'.format(layer_num),
				nn.Tanh())

		self.conv_dec = conv_dec
		self.conv_last = conv_last


	def forward(self, x, latent=False):
		# t = self.fc(x).view(self.batch_size, self.init_channels, 16)
		t = self.fc(x).view(x.shape[0], self.init_channels, 16)
		latent_out = self.conv_dec(t)
		out = self.conv_last(latent_out)
		if latent:
			return latent_out, out
		else:
			return out


class MultiResBlock1d(nn.Module):

	def __init__(self, name, in_channels, out_channels, blocktype, activation):
		super(MultiResBlock1d, self).__init__()

		self.upsample = Ops.NNUpsample1d()
		self.pool = nn.MaxPool1d(kernel_size=4, stride=4)
		self.in_channels = in_channels
		self.out_channels = out_channels
		self.name = name

		self.conv0 = nn.Sequential()
		self.conv0.add_module('{}_conv0'.format(self.name),
				blocktype(self.in_channels*2,
					self.out_channels,
					kernel_size=2,
					stride=2,
					padding=0))
		self.conv0.add_module('{}_bn0'.format(self.name),
				nn.BatchNorm1d(self.out_channels))
		self.conv0.add_module('{}_activation0'.format(self.name),
				activation)

		self.conv1 = nn.Sequential()
		self.conv1.add_module('{}_conv1'.format(self.name),
				blocktype(self.in_channels*3,
					self.out_channels,
					kernel_size=2,
					stride=2,
					padding=0))
		self.conv1.add_module('{}_bn1'.format(self.name),
				nn.BatchNorm1d(self.out_channels))
		self.conv1.add_module('{}_activation1'.format(self.name),
				activation)

		self.conv2 = nn.Sequential()
		self.conv2.add_module('{}_conv2'.format(self.name),
				blocktype(self.in_channels*2,
					self.out_channels,
					kernel_size=2,
					stride=2,
					padding=0))
		self.conv2.add_module('{}_bn2'.format(self.name),
				nn.BatchNorm1d(self.out_channels))
		self.conv2.add_module('{}_activation2'.format(self.name),
				activation)

	def forward(self, x):
		x0 = x[0]
		x1 = x[1]
		x2 = x[2]

		in0 = torch.cat((x0, self.upsample(x1)), 1)
		in1 = torch.cat((self.pool(x0), x1, self.upsample(x2)), 1)
		in2 = torch.cat((self.pool(x1), x2), 1)

		out0 = self.conv0(in0)
		out1 = self.conv1(in1)
		out2 = self.conv2(in2)

		return [out0, out1, out2]


class MultiResConv1d(MultiResBlock1d):

	def __init__(self, name, in_channels, out_channels, activation=nn.ReLU(inplace=True)):
		super(MultiResConv1d, self).__init__(
				name, in_channels, out_channels, nn.Conv1d, activation=activation)


class MultiResConvTranspose1d(MultiResBlock1d):

	def __init__(self, name, in_channels, out_channels, activation=nn.ReLU(inplace=True)):
		super(MultiResConvTranspose1d, self).__init__(
				name, in_channels, out_channels, nn.ConvTranspose1d, activation=activation)


class PointCloudAutoEncoderVAE(Model):

	def __init__(self, size, dim, batch_size=64, enc_size=100, kernel_size=16,
			noise=0,
			name="PCAutoEncoder"):
		super(PointCloudAutoEncoder, self).__init__(name)

		self.size = size
		self.dim = dim
		self.batch_size = batch_size
		self.kernel_size = kernel_size
		self.enc_size =  enc_size
		self.noise_factor = noise
		self.enc_noise = torch.FloatTensor(self.batch_size, self.enc_size)

		self.encoder = PointCloudEncoder(self.size, self.dim,
				batch_size = self.batch_size,
				enc_size = self.enc_size,
				kernel_size = self.kernel_size)

		self.decoder = PointCloudDecoder(self.size, self.dim,
				batch_size = self.batch_size,
				enc_size = self.enc_size,
				kernel_size = self.kernel_size)

		self.fc_mu = nn.Linear(self.enc_size, self.enc_size)
		self.fc_logvar = nn.Linear(self.enc_size, self.enc_size)

	def encode(self, x):
		h1 = self.encoder(x)
		return self.fc_mu(h1), self.fc_logvar(h1)

	def reparameterize(self, mu, logvar):
		std = torch.exp(0.5*logvar)
		eps = torch.randn_like(std)
		return mu + eps*std

	def decode(self, z, latent=False):
		return self.decoder(z, latent)

	def forward(self, x, latent=False):
		# x = x.view(-1, 1024 * 3) # shoul be in the training
		mu, logvar = self.encode(x)
		z = self.reparameterize(mu, logvar)
		return self.decode(z, latent), mu, logvar


class PointCloudAutoEncoder(Model):

	def __init__(self, size, dim, batch_size=64, enc_size=100, kernel_size=16,
			noise=0,
			name="PCAutoEncoder"):
		super(PointCloudAutoEncoder, self).__init__(name)

		self.size = size
		self.dim = dim
		self.batch_size = batch_size
		self.kernel_size = kernel_size
		self.enc_size =  enc_size
		self.noise_factor = noise
		self.enc_noise = torch.FloatTensor(self.batch_size, self.enc_size)

		self.encoder = PointCloudEncoder(self.size, self.dim,
				batch_size = self.batch_size,
				enc_size = self.enc_size,
				kernel_size = self.kernel_size)

		self.decoder = PointCloudDecoder(self.size, self.dim,
				batch_size = self.batch_size,
				enc_size = self.enc_size,
				kernel_size = self.kernel_size)

		self.tanh = nn.Tanh()

	def encode(self, x):
		# [-1, 1]
		return self.tanh(self.encoder(x))

	def decode(self, z):
		return self.decoder(z)

	def forward(self, x):
		# x = x.view(-1, 1024 * 3) # shoul be in the training
		z = self.encode(x)
		return self.decode(z)

class NormalReg(nn.Module):

	def __init__(self):
		super(NormalReg, self).__init__()

	def forward(self, x):

		mean = torch.mean(x, dim=0).pow(2)
		cov = Ops.cov(x)

		cov_loss = torch.mean(
				(Variable(torch.eye(cov.size()[0]).cuda())-cov)
				.pow(2))

		return torch.mean(mean) + cov_loss


class PointCloudVAE(PointCloudAutoEncoder):

	def __init__(self, size, dim, batch_size=64, enc_size=100, kernel_size=16,
			reg_fn=NormalReg(),
			noise = 0,
			name="PCVAE"):
		super(PointCloudVAE, self).__init__(size, dim, batch_size, enc_size, kernel_size,
				noise=noise, name=name)
		self.reg_fn = reg_fn
		self.noise = torch.FloatTensor(self.batch_size, self.enc_size)


	def encoding_regularizer(self, x):
		return self.reg_fn(self.encoder(x))


	def sample(self, latent=False):
		self.noise.normal_()
		return self.decoder(Variable(self.noise.cuda()), latent)




class EncodingSVM(Model):

	def __init__(self, enc_size, n_classes, ae_model, batch_size, name="EncSVM"):
		super(EncodingSVM, self).__init__(name)

		self.batch_size = batch_size
		self.enc_size = enc_size
		self.n_classes = n_classes
		self.ae_model = ae_model

		self.upsample = Ops.NNUpsample1d()

		alpha = 32
		self.pools = []
		self.pools.append(nn.MaxPool1d(kernel_size=alpha, stride=alpha))
		self.pools.append(nn.MaxPool1d(kernel_size=alpha/2, stride=alpha/2))
		self.pools.append(nn.MaxPool1d(kernel_size=alpha/4, stride=alpha/4))
		#self.pools.append(nn.MaxPool1d(kernel_size=alpha/8, stride=alpha/8))

		self.fc = nn.Linear(self.enc_size, self.n_classes)

	def forward(self, x):
		enc, features = self.ae_model.enc_forward(x)
		descriptor = []
		for i, p in enumerate(self.pools):
			t0 = p(features[i][0])
			t1 = self.upsample(p(features[i][1]))
			t2 = self.upsample(self.upsample(p(features[i][2])))
			descriptor.append(torch.cat((t0, t1, t2), 1))

		descriptor = torch.cat(descriptor, 1)
		descriptor = descriptor.view(self.batch_size, -1)

		return self.fc(descriptor)