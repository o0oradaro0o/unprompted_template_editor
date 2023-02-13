from modules.shared import cmd_opts
class Shortcode():
	def __init__(self,Unprompted):
		self.Unprompted = Unprompted
		self.description = "A neural network structure to control diffusion models by adding extra conditions."
		self.detect_resolution = 512
		self.save_memory = False
		self.steps = 20
		self.can_run = False
		self.temp_no_half = False
	
	def run_atomic(self, pargs, kwargs, context):
		if "init_images" not in self.Unprompted.shortcode_user_vars:
			self.Unprompted.log("This shortcode is only supported in img2img mode.","ERROR")

		
		# Hacky way of bypassing the normal img2img routine
		self.steps = self.Unprompted.shortcode_user_vars["steps"]
		self.Unprompted.shortcode_user_vars["steps"] = 1
		self.can_run = True

		# Workaround for half precision error
		self.temp_no_half = cmd_opts.no_half
		cmd_opts.no_half = True

		if "detect_resolution" in kwargs: self.detect_resolution = kwargs["detect_resolution"]
		if "save_memory" in pargs: self.save_memory = True
		return("")

	def after(self,p=None,processed=None):
		if "init_images" not in self.Unprompted.shortcode_user_vars:
			self.Unprompted.log("This shortcode is only supported in img2img mode.","ERROR")
		import torch
		import cv2
		import einops
		import numpy as np
		import lib_unprompted.stable_diffusion.controlnet.config as config
		from PIL import Image

		from modules.images import flatten
		from modules.shared import opts, sd_model

		from lib_unprompted.stable_diffusion.controlnet.annotator.util import resize_image, HWC3
		from lib_unprompted.stable_diffusion.controlnet.annotator.openpose import apply_openpose
		from lib_unprompted.stable_diffusion.controlnet.cldm.model import create_model, load_state_dict
		from lib_unprompted.stable_diffusion.controlnet.ldm.models.diffusion.ddim import DDIMSampler

		# from modules import sd_models

		import sys
		sys.path.append(f"{self.Unprompted.base_dir}/lib_unprompted/stable_diffusion/controlnet")

		from modules import sd_models
		info = sd_models.get_closet_checkpoint_match("control_sd15_openpose")
		if (info): sd_models.reload_model_weights(None,info)
		sd_model = sd_model.cuda()
		ddim_sampler = DDIMSampler(sd_model)

		image_resolution = min(self.Unprompted.shortcode_user_vars["width"],self.Unprompted.shortcode_user_vars["height"])

		num_samples = self.Unprompted.shortcode_user_vars["batch_size"]

		with torch.no_grad():
			for img in self.Unprompted.shortcode_user_vars["init_images"]:
				img = np.asarray(flatten(img, opts.img2img_background_color))

				input_image = HWC3(img)
				detected_map, _ = apply_openpose(resize_image(input_image, self.detect_resolution))
				detected_map = HWC3(detected_map)
				img = resize_image(input_image, image_resolution)
				H, W, C = img.shape

				detected_map = cv2.resize(detected_map, (W, H), interpolation=cv2.INTER_NEAREST)

				control = torch.from_numpy(detected_map.copy()).float().cuda() / 255.0
				control = torch.stack([control for _ in range(num_samples)], dim=0)
				control = einops.rearrange(control, 'b h w c -> b c h w').clone()

				if self.save_memory:
					sd_model.low_vram_shift(is_diffusing=False)

				cond = {"c_concat": [control], "c_crossattn": [sd_model.get_learned_conditioning([self.Unprompted.shortcode_user_vars["prompt"]] * num_samples)]}
				un_cond = {"c_concat": [control], "c_crossattn": [sd_model.get_learned_conditioning([self.Unprompted.shortcode_user_vars["negative_prompt"]] * num_samples)]}
				shape = (4, H // 8, W // 8)

				if self.save_memory:
					sd_model.low_vram_shift(is_diffusing=True)

				samples, intermediates = ddim_sampler.sample(self.steps, num_samples,
															shape, cond, verbose=False, eta=self.Unprompted.shortcode_user_vars["denoising_strength"],
															unconditional_guidance_scale=self.Unprompted.shortcode_user_vars["cfg_scale"],
															unconditional_conditioning=un_cond)

				if self.save_memory:
					sd_model.low_vram_shift(is_diffusing=False)

				x_samples = sd_model.decode_first_stage(samples)
				x_samples = (einops.rearrange(x_samples, 'b c h w -> b h w c') * 127.5 + 127.5).cpu().numpy().clip(0, 255).astype(np.uint8)

				for i in range(num_samples):
					output = Image.fromarray(x_samples[i])
					output_map = Image.fromarray(detected_map)
					processed.images.append(output)
					processed.images.append(output_map)

		# Set back to user defined value
		cmd_opts.no_half = self.temp_no_half
		
		# processed.images.append([detected_map])
		return(processed)

	def cleanup(self):
		self.save_memory = False

	def ui(self,gr):
		pass