| Model | Target macro-F1 | F1@50 | Edit (order) | Boundary F1 @2s | ECE raw → calibrated |
|---|---|---|---|---|---|
| clip_tcn | 42.3 | 34.3 | 45.7 | 43.6 | 3.9 → 4.9 |
| resnet_bilstm | 37.9 | 30.9 | 44.3 | 39.7 | 15.6 → 5.5 |
| xclip_linear | 37.4 | 26.0 | 46.2 | 49.0 | 10.4 → 5.4 |
| clip_bilstm | 44.3 | 34.9 | 47.8 | 42.3 | 11.7 → 5.9 |
| clip_zero_shot | 16.7 | 7.4 | 29.8 | 28.6 | – → 16.3 |

Per skill (main model, clip_tcn):

| Skill | macro-F1 | F1@50 | Edit | Accuracy | Test videos |
|---|---|---|---|---|---|
| ReplaceMobileScreenProtector | 42.2 | 27.1 | 47.1 | 60.0 | 23 |
| PerformCPR | 37.5 | 38.5 | 45.2 | 74.8 | 17 |
| PolishCar | 47.1 | 37.4 | 44.8 | 78.7 | 15 |
| MakePizza | 62.2 | 39.0 | 52.8 | 72.0 | 20 |
| UseRiceCookerToCookRice | 53.5 | 38.6 | 57.4 | 66.3 | 14 |
| BoilNoodles | 44.3 | 40.0 | 25.0 | 85.4 | 1 |

Videos per skill vs score (clip_tcn):

| Videos per skill | macro-F1 | F1@50 |
|---|---|---|
| 5 | 25.5 | 10.1 |
| 10 | 29.6 | 21.0 |
| 20 | 33.6 | 28.1 |
| all | 43.9 | 32.9 |

Few-shot on unseen task (CookOmelet):

| Method | macro-F1 | F1@50 | Edit |
|---|---|---|---|
| prototype_K0 | 15.7 | 1.2 | 12.5 |
| prototype_K1 | 18.6 | 9.7 | 31.2 |
| prototype_K5 | 25.6 | 14.4 | 35.2 |
| finetune_K5 | 28.5 | 21.2 | 33.3 |
| prototype_K10 | 25.8 | 11.0 | 36.1 |
| finetune_K10 | 31.0 | 21.3 | 35.1 |
