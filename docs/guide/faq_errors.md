# FAQs and Common Errors/Warnings

## FAQs

  - **Q**: How does logging work? How do I use Tensorboard or Weights and Biases?

    **A**: Logging is configured under the `trainer` section of the config file by specifying the `logger` argument of the `lightning.Trainer` (see [API](https://lightning.ai/docs/pytorch/stable/common/trainer.html#trainer-class-api)). Compatible loggers are found [here](https://lightning.ai/docs/pytorch/stable/api_references.html#loggers). Read the [Config](config.md) docs for a more complete description.


  - **Q**: What units do `nequip` framework models use?

    **A**: `nequip` has no prefered system of units and uses the units of the data provided. Model inputs, outputs, error metrics, and all other quantities follow the units of the dataset. Users **must** use consistent input and output units. For example, if the length unit is Å and the energy labels are in eV, the force predictions from the model will be in eV/Å. The provided force labels should hence also be in eV/Å. 

	```{warning}
	`nequip` cannot and does not check the consistency of units in inputs you provide, and it is your responsibility to ensure consistent treatment of input and output units
	```

  - **Q**: What floating point precision (`torch.dtype`) is used in the `nequip` framework?
  
    **A**: `float64` precision is used for data (inputs to model and reference labels). Either `float32` or `float64` precision can be used as the `model_dtype` (which is a mandatory hyperparameter of models in the `nequip` framework). If `float32` precision is used for `model_dtype`, the model will cast down from the `float64` inputs (e.g. positions) and cast up the outputs (e.g. energy) to `float64`. A major change in the post-revamp `nequip` framework is that NequIP or Allegro models keep the initial embeddings in `float64` before casting down if `model_dtype=float32` for better numerics.

## Commons Errors

  - **Problem**: Trying to run `nequip-train` as follows fails.
    ```bash
	nequip-train config.yaml
	```
	**Solution**: Read the [workflow docs](workflow.md) and follow hydra's command line options, e.g.
	```bash
	nequip-train -cn config.yaml
	```

## Common Warnings


### Other

  - Setting global configuration settings
    
    Warnings of the form
    ```txt
    Setting the GLOBAL value for ...
    ```
    `nequip` manages a number of global configuration settings of PyTorch and e3nn and correctly restores those values when a deployed model is loaded. These settings, however, must be set at a global level and thus may affect a host application;  for this reason `nequip` by default will warn whenever overriding global configuration options.  If you need to, these warnings can be silenced with `set_global_options=True`.  (Setting `set_global_options=False` is **strongly** discouraged and might lead to strange issues or incorrect numerical results.)