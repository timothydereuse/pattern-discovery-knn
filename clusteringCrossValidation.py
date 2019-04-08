import torch
import pickle
import clusteringTest as ct
import distanceLearningNet as dln
import prepareDataForTraining as pdft
import netClasses as nc
from importlib import reload
reload(ct)
reload(dln)
reload(pdft)
reload(nc)

import numpy as np

num_validation_sets = 6  # number of experiments to run
val_ratio = 0.075          # use this much of each training set for validation
feature_subset = 'exclude_seqs'
dim_size = 10
stagnation_time = 2000
batch_size = 256

pairs_unsimilar_factor = 1
pairs_trivial_factor = 1
pairs_max_similar = 0

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device = torch.device("cpu")
pickle_name = 'parsed_patterns.pik'

# load from pickle
print("loading data from file...")
with open(pickle_name, "rb") as f:
    dat = pickle.load(f)
songs = dat[0]
pClasses = dat[1]
pOccs = dat[2]
annPClassNames = dat[3]
annPOccNames = dat[4]
genPClassNames = dat[5]
genPOccNames = dat[6]
song_to_tunefam = dat[7]
sorted_fkeys = sorted(list(pOccs.values())[0].occFeatures.keys())
tune_fams = list(set(song_to_tunefam.values()))

# break up into sets
fams_shuffle = np.array(tune_fams)
np.random.shuffle(fams_shuffle)
fams_sets = np.array_split(fams_shuffle, num_validation_sets)


# break up into sets
idx_shuffle = np.array(range(len(annPClassNames)))
np.random.shuffle(idx_shuffle)
set_idxs = np.array_split(idx_shuffle, num_validation_sets)

all_results = []
pca_results = []

for run_num in range(num_validation_sets * 0 + 3):
    print("starting run {}...".format(run_num))

    # test_idxs = np.concatenate(set_idxs[:-1])
    test_fams = fams_sets[0]
    train_fams = np.concatenate(fams_sets[1:])
    fams_sets = np.roll(fams_sets, 1)    # prepare for the next test by rotating test/train

    # get pairwise similarity/unsimilarity data for training set
    train_class_names = [x for x in annPClassNames if (pClasses[x].tuneFamily in train_fams)]
    test_class_names = [x for x in annPClassNames if (pClasses[x].tuneFamily in test_fams)]

    train_gen_class_names = [x for x in genPClassNames if (pClasses[x].tuneFamily in train_fams)]
    test_gen_class_names = [x for x in genPClassNames if (pClasses[x].tuneFamily in test_fams)]

    # split train further into a small val set
    val_split_idx = int(len(train_class_names) * val_ratio)
    val_class_names = train_class_names[:val_split_idx]
    train_class_names = train_class_names[val_split_idx:]

    train_data, train_labels = pdft.assemble_clustering_feats(dat,
        train_class_names,
        train_gen_class_names,
        unsimilar_factor=pairs_unsimilar_factor,
        gen_factor=pairs_trivial_factor,
        max_similar=pairs_max_similar,
        subset=feature_subset)

    val_data, val_labels = pdft.assemble_clustering_feats(dat,
        val_class_names,
        train_gen_class_names,
        unsimilar_factor=pairs_unsimilar_factor,
        gen_factor=pairs_trivial_factor,
        max_similar=pairs_max_similar,
        subset=feature_subset)


    # make the model
    model = nc.FFNetDistance(num_feats=train_data.shape[-1], dim_size=dim_size)
    model.to(device)

    # pair_idx_shuffle = np.array(range(len(train_data)))
    # np.random.shuffle(pair_idx_shuffle)
    # val_pair_idxs = pair_idx_shuffle[:val_split_idx]
    # train_pair_idxs = pair_idx_shuffle[val_split_idx:]
    #
    # x_train = torch.tensor(train_data[train_pair_idxs]).float()
    # y_train = torch.tensor(train_labels[train_pair_idxs]).long()
    # x_val = torch.tensor(train_data[val_pair_idxs]).float()
    # y_val = torch.tensor(train_labels[val_pair_idxs]).long()

    x_train = torch.tensor(train_data).float()
    y_train = torch.tensor(train_labels).long()
    x_val = torch.tensor(val_data).float()
    y_val = torch.tensor(val_labels).long()

    model, accs = dln.train_model((x_train, y_train), model, device,
        batch_size=batch_size,
        num_epochs=50000,
        stagnation_time=stagnation_time,
        poll_every=500,
        val_every=100,
        lr=2e-4,
        val_data=(x_val, y_val)
        )

    # TESTING
    # assemble test occurrences

    torch.save(model.state_dict(),'models\model{}.pt'.format(run_num))
    model.eval()  # set model to evaluation mode

    epsilon = ct.estimate_best_epsilon((x_val, y_val), model)
    epsilons = np.geomspace(0.0001, epsilon/4, 100)
    pca_epsilons = np.geomspace(0.000001, 100, 100)

    # create test set of cluster-labeled occurrences
    test_occs = []
    labels_true = []
    for i, pn in enumerate(test_class_names):
        occNames = pClasses[pn].occNames
        for on in occNames:
            test_occs.append(on)
            labels_true.append(i)
    # add noisy occs from the same tunefam
    for pn in test_gen_class_names:
        occNames = pClasses[pn].occNames
        for on in occNames:
            test_occs.append(on)
            labels_true.append(-1)

    # add noisy occs:
    # for i in range(len(test_occs) * 0):
    #     test_occs.append(str(np.random.choice(genPOccNames)))
    #     labels_true.append(-1)

    res = ct.evaluate_clustering(test_occs, labels_true, model, pOccs, feature_subset, epsilons=epsilons)
    print(res)
    all_results.append(res)

    pca_res = ct.evaluate_clustering_pca(test_occs, labels_true, pOccs,
        n_components=dim_size, subset=feature_subset, epsilons=pca_epsilons)
    print(pca_res)
    pca_results.append(pca_res)

print('EMBEDDING:')
for key in res[0].keys():
    category = [x[0][key] for x in all_results]
    mean = np.round(np.mean(category),3)
    stdv = np.round(np.std(category),3)
    print(key, mean, stdv)

print('PCA:')
for key in res[0].keys():
    category = [x[0][key] for x in pca_results]
    mean = np.round(np.mean(category),3)
    stdv = np.round(np.std(category),3)
    print(key, mean, stdv)