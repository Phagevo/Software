import esm
import torch
import os 
import shutil
from torch.utils.data import DataLoader
from functools import partial
import numpy as np

from PocketGen.models.PD import Pocket_Design_new
from PocketGen.utils.misc import seed_all, load_config
from PocketGen.utils.transforms import FeaturizeProteinAtom, FeaturizeLigandAtom
from PocketGen.utils.data import collate_mols_block

from .sampler import interaction
from eval.docking import docking
from eval.prepare import prepare
from eval.window import compute_box
from eval.mutations import mutations
from eval.chemutils import kd

class Model:
  def __init__(self, checkpoint_path:str, args):
    """
    The mutant generation model constructor. This method does the setup of 
    torch and CUDA environment, loads the checkpoint and then returns a PocketGen 
    instance using the weights from checkpoints and the parameters retrieved.
    @param checkpoint_path (str): Path to checkpoint (.pt) file for PocketGen.
    @param verbose (int): 0 for quiet, 1 for necessary information and 2 for debug.
    """

    # setup global class variables
    self.verbose = args["verbose"]
    self.device = args["device"]
    self.outputdir = args["output"]
    self.size = args["number"]
    self.sources = []
    self.config = load_config('./PocketGen/configs/train_model.yml')
    
    if self.verbose > 0:
      print('Flint setup started, please wait.')
    if self.verbose == 2:
      print('Now initializing pytorch and CUDA environment :')

    # cleans cache and sets the libs seeds
    torch.cuda.empty_cache()
    seed_all(2089)

    if self.verbose == 2:
      print('\tpytorch and CUDA initialized correctly.')
      print('Now retrieving alphabet from fair-ESM :')

    # sets ESM2 alphabet as the usual alphabet
    pretrained_model, self.alphabet = esm.pretrained.load_model_and_alphabet_hub('esm2_t33_650M_UR50D')
    del pretrained_model # ESM2 pretrained_model that we don't need here is deleted from memory

    if self.verbose == 2:
      print('\tESM alphabet successfully loaded.')
      print('Now building PocketGen model :')

    # get the model checkpoint from .pt file
    self.checkpoint = torch.load(checkpoint_path, map_location=self.device)

    if self.verbose == 2:
      print('\tcheckpoint successfully created.')

    # instanciate PocketGen model for pocket design
    self.model = Pocket_Design_new(
      self.config.model,
      protein_atom_feature_dim=FeaturizeProteinAtom().feature_dim,
      ligand_atom_feature_dim=FeaturizeLigandAtom().feature_dim,
      device=self.device
    )

    if self.verbose == 2:
      print("\tPocketGen model well instanciated.")

    # send model to selected device
    self.model = self.model.to(self.device)

    if self.verbose == 2:
      print('\tPocketGen model sent to selected device.')

    # load current saved checkpoint into model
    self.model.load_state_dict(self.checkpoint['model'])

    if self.verbose == 2:
      print('\tcheckpoint loaded into PocketGen.')
      print('End of setup, model can now be used.\n\n')
  

  def input(self, receptor_path:str, ligand_path:str) -> "Model":
    """
    Loads a protein receptor and a ligand from files and store it in 
    a data-loader, useable by the model when generating mutants.
    @param ligand_path (str): path to the ligand SDF file.
    @param receptor_path (str): path to the receptor PDB file.
    @return (Model): the instance of Model, for chainability purposes.
    """

    if self.verbose == 2:
      print('Now parsing data from receptor and ligand :')
    
    # get dense features from receptor-ligand interaction
    features = interaction(receptor_path, ligand_path)

    if self.verbose == 2:
      print('\tsuccessfully parsed interaction features.\n')
      print('Now building the pytorch dataloader :')

    # initialize the data loader (including batch converter)
    self.loader = DataLoader(
      [features for _ in range(self.size)],
      batch_size=1, 
      shuffle=False,
      num_workers=self.config.train.num_workers,
      collate_fn=partial( # use multiprocessing to parallelize
        collate_mols_block, # core of the batching process
        batch_converter=self.alphabet.get_batch_converter()
      )
    )

    # stores the source input files to compare
    self.sources = [receptor_path, ligand_path]

    if self.verbose == 2:
      print('\tpytorch dataloader built correctly.')

    return self

  
  def generate(self) -> "Model":
    """
    Generates mutants based on the input protein receptor.
    @return (Model): the instance of Model, for chainability purposes.
    """

    if self.verbose > 0:
      print("Now generating new mutant protein receptors :")

    # place it in eval mode
    self.model.eval()

    # creates the inference directory
    n_runs = self._nruns()
    run_dir = os.path.join(self.outputdir, f"run_{n_runs}")
    os.makedirs(run_dir)

    # no need to compute gradients during inference
    with torch.no_grad():
      for b, batch in enumerate(self.loader):
        # move batch to selected device
        batch = {k: v.to(self.device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

        # starts the inference for a single mutant
        self.model.generate(
          batch, target_path=os.path.join(run_dir, f"mutant_{b}")
        )
        
        if self.verbose > 0:
          print(f"\tinference done on a batch.")
        
    # stores the original input files for comparison
    os.makedirs(os.path.join(run_dir, "original"), exist_ok=True)
    shutil.copyfile(self.sources[0], os.path.join(run_dir, "original", "orig_receptor.pdb"))
    shutil.copyfile(self.sources[1], os.path.join(run_dir, "original", "orig_ligand.sdf"))

    # write inputs details to a local file
    with open(os.path.join(run_dir, "inputs.txt"), "w") as file:
      file.write(f"RECEPTOR: {self.sources[0]}\nLIGAND: {self.sources[1]}")

    return self
  
  
  def results(self) -> "Model":
    """
    write results in a summary file, along with all generated PDBs.
    @return (Model): the instance of Model, for chainability purposes.
    """

    if self.verbose > 0:
      print(f"Now writing output files :")
    
    for run in range(self._nruns()):
      run_dir = os.path.join(self.outputdir, f"run_{run}")
      
      if os.path.isfile(os.path.join(run_dir, "summary.tsv")):
        continue

      # initialize the resulting summary TSV
      summary = "ID\tdelta_G\tKd\tmutations (AA)\n"

      # write original inputs docking in summary
      src_mean_dg, src_mean_kd = self._dock(
        os.path.join(run_dir, "original", f"orig_receptor.pdb"),
        os.path.join(run_dir, "original", "orig_ligand.sdf")
      )

      summary += f"original\t{src_mean_dg}\t{src_mean_kd}\t0" + "\n"

      for b in range(self._nbatches(run_dir)):
        receptor_path = os.path.join(run_dir, f"mutant_{b}", f"{b}_whole.pdb")
        ligand_path = os.path.join(run_dir, f"mutant_{b}", f"{b}.sdf")

        mean_dg, mean_kd = self._dock(receptor_path, ligand_path)

        # find the number of mutations (AA-level)
        n_mutations = mutations(
          os.path.join(run_dir, "original", f"orig_receptor.pdb"),
          receptor_path
        )

        summary += f"mutant_{b}\t{mean_dg}\t{mean_kd}\t{n_mutations}" + "\n"

        if self.verbose == 2:
          print(f"\twrote one new entry in the summary file.")
      
      # write summary to a local file
      with open(os.path.join(run_dir, "summary.tsv"), "w") as file:
        file.write(summary)

      if self.verbose > 0:
        print(f"You can find the run #{run} summary in your output folder.")

    return self
  

  def _dock(self, receptor_path, ligand_path):

    # compute the docking window around ligand
    docking_box = compute_box(receptor_path, ligand_path)

    try:
      energies = docking(
        receptor_file=prepare(receptor_path),
        ligand_file=prepare(ligand_path),
        center=docking_box["center"],
        box_size=docking_box["size"],
        verbosity=self.verbose
      )
    except Exception as e:
      print(f"\t\terror simulating docking: {e}")
      energies = np.zeros(1)

    # calculates the mean Kd and deltaG
    return np.mean(energies), np.mean([kd(e) for e in energies])


  def _nruns(self) -> int:
    """
    returns the number of inferences stored from now in the output directory
    @return (int): the number of folders in dir
    """

    os.makedirs(self.outputdir, exist_ok=True)
    return len([f for f in os.listdir(self.outputdir) if os.path.isdir(os.path.join(self.outputdir, f))])


  def _nbatches(self, run_path) -> int:
    """
    returns the number of inferences stored from now in the output directory
    @return (int): the number of folders in dir
    """

    os.makedirs(run_path, exist_ok=True)
    return len([f for f in os.listdir(run_path) if os.path.isdir(os.path.join(run_path, f))]) - 1

