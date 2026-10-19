---
title: fruit_fly
emoji: 🪰
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
license: cc-by-nc-4.0
short_description: How a fruit fly learns to avoid an odour, on its real wiring
---

# fruit_fly: a fruit fly learning, spike by spike

A spiking model of the fruit fly's mushroom body, the brain area where flies learn which odours predict a shock or a reward. Every neuron and synapse (8,603 neurons, ~760k connections) comes from the [FlyWire](https://flywire.ai) whole-brain connectome, and odours are real receptor responses from [DoOR](https://neuro.uni-konstanz.de/DoOR).

Pick two odours from the menu, pair one with a shock or a sugar reward, and watch the circuit learn in 3D: every neuron is drawn as its real shape inside the brain's regions, and clicking one shows what it connects to. Then read off what the fly would do in a T-maze. You can also silence neurons, try extinction, blocking or backward pairing, and sweep a parameter.

**This is a shared public demo.**
- Each address may start a limited number of experiments per minute, and a small queue is shared by everyone.
- Only you can cancel or delete what you started.
- Experiments are kept until the Space restarts.
- An experiment on the real circuit takes about 20–40 s.

Code, design notes and the validation against 12 published findings: see the project repository.

## Data and credits

- **Connectome:** FlyWire FAFB v783. Dorkenwald et al. 2024, *Nature* 634:124; Schlegel et al. 2024, *Nature* 634:139. Licensed **CC BY-NC 4.0**, which is why this Space is non-commercial.
- **Neuron shapes:** the FlyWire v783 skeletons of the Cambridge FlyConnectome group (Schlegel et al. 2024), simplified. **Brain regions:** FlyWire's neuropil meshes, the neuropils of Ito et al. 2014, *Neuron* 81:755.
- **Neurotransmitter predictions:** Eckstein et al. 2024, *Cell* 187:2574.
- **Odour responses:** DoOR 2.0, Münch & Galizia 2016, *Sci Rep* 6:21841 (CC BY-SA 4.0).
- **Neuron model parameters:** Shiu et al. 2024, *Nature* 634:210.
