# 🚀 __PJNAME__ : AI-powered protein receptor mutation

A computational tool designed to generate protein receptor mutants that allows enhanced binding specificity towards a target ligand, based on [PocketGen]. While generating a set of mutated receptor structures, __PJNAME__ evaluates their affinity with the ligand using [AutoDock Vina]. The key point is that the docking simulation is embedded as a scoring function, making it the target of the gradient descent.

## Outputs and expected results

If executed correctly, __PJNAME__ will generate the following outputs:

1. A set of unique mutated receptor proteins in PDB format, designed to maximize the binding affinity for the ligand.
2. A summary file containing, for each receptor :
   - The corresponding docking score, affinity constant and rank compared to other mutants.
   - Additional information about the receptor-ligand interaction (e.g. ligand position, residues involved).
   - The sequence of mutations that leads to its creation, starting from the original receptor.

## Getting started with __PJNAME__

```bash
git clone __PJURL__
cdn __PJNAME__
```
Install the environment and dependencies using [conda]'s config file
```bash
conda env create -f env.yaml
conda activate __PJNAME__
```
If you intend to build environment without conda, keep in mind that installing [AutoDock Vina] from `pip` or any other package manager is deprecated. Besides, to run the project from Windows, [this question](https://stackoverflow.com/questions/71865073/unable-to-install-autodock-vina-potentially-due-to-boost) on stackoverflow might be helpful.
```yaml
├── pocketgen # can be cloned from PocketGen repository
├── checkpoints 
│   └── checkpoint.pt # needs to be downloaded manually
│
├── eval
├── model
└── __PJNAME__.py
```
This (above) is what should ressemble your working directory after installing __PJNAME__.

## Usage from command line
```bash
python __PJNAME__.py --receptor <receptor.pdb> --ligand <ligand.pdbqt> --output <output_directory>
```
- `<receptor.pdb>`: Path to the input protein receptor file in PDB format.
- `<ligand.pdbqt>`: Path to the input ligand file in SDF format.
- `<output_directory>`: Directory where the output mutant structures and scores will be saved.

[AutoDock Vina]: https://github.com/ccsb-scripps/AutoDock-Vina
[PocketGen]: https://github.com/zaixizhang/PocketGen