import torch
import pickle
import clusteringTest as ct
import distanceLearningNet as dln
import prepareDataForTraining as pdft
import netClasses as nc
from importlib import reload
import numpy as np
import datetime
reload(ct)
reload(dln)
reload(pdft)
reload(nc)


fname = 'models/run {}.txt'.format(datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
pickle_name = 'parsed_patterns.pik'
num_validation_sets = 5             # number of experiments to run
val_ratio = 0.1                     # use this much of each training set for validation
feature_subset = 'all'              # key indicating features to use (see prepareDataForTraining)
dim_size = 5                        # dimensionality of subspace
stagnation_time = 1000              # stop training when val set doesn't improve in N iterations
batch_size = 256
percentiles = [75, 80, 85, 90, 95]  # for estimating values of epsilon for DBSCAN

reduce_with_pca = -1                # an interesting idea that didn't work

pairs_unsimilar_factor = 1          # how many pairs of significant occs from diff pattern?
pairs_trivial_factor = 1            # pairs of significant/trivial occs from different patterns?
pairs_intra_trivial_factor = 0      # pairs of trivial occs from different patterns?
pairs_max_similar = 0               # limit size of pair sets (0 = off)

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device = torch.device("cpu")  # GPU doesn't really help here

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

all_results = []
pca_results = []

for run_num in range(1): #num_validation_sets):
    print("starting run {}...".format(run_num))

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
    np.random.shuffle(train_class_names)
    val_class_names = train_class_names[:val_split_idx]
    train_class_names = train_class_names[val_split_idx:]

    train_data, train_labels = pdft.assemble_clustering_feats(dat,
        train_class_names,
        train_gen_class_names,
        unsimilar_factor=pairs_unsimilar_factor,
        gen_factor=pairs_trivial_factor,
        intra_gen_factor=pairs_intra_trivial_factor,
        max_similar=pairs_max_similar,
        subset=feature_subset,
        reduce_with_pca=reduce_with_pca)

    val_data, val_labels = pdft.assemble_clustering_feats(dat,
        val_class_names,
        train_gen_class_names,
        unsimilar_factor=pairs_unsimilar_factor,
        gen_factor=pairs_trivial_factor,
        intra_gen_factor=pairs_intra_trivial_factor,
        max_similar=pairs_max_similar,
        subset=feature_subset,
        reduce_with_pca=reduce_with_pca)

    # make the model
    model = nc.FFNetDistance(num_feats=train_data.shape[-1], dim_size=dim_size)
    model.to(device)

    x_train = torch.tensor(train_data).float()
    y_train = torch.tensor(train_labels).long()
    x_val = torch.tensor(val_data).float()
    y_val = torch.tensor(val_labels).long()

    model, accs = dln.train_model((x_train, y_train), model, device,
        batch_size=batch_size,
        num_epochs=50000,
        stagnation_time=stagnation_time,
        poll_every=500,
        val_every=50,
        lr=1e-4,
        val_data=(x_val, y_val)
        )

    # TESTING
    # assemble test occurrences

    torch.save(model.state_dict(), 'models\model{}.pt'. format(run_num))
    model.eval()  # set model to evaluation mode

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

    res, emb_labellings = ct.evaluate_clustering(test_occs, labels_true, model, pOccs,
        feature_subset, eps_pctiles=percentiles, reduce_with_pca=reduce_with_pca)
    # print(res)
    all_results.append(res)

    pca_res, pca_labellings = ct.evaluate_clustering_pca(test_occs, labels_true, pOccs,
        n_components=dim_size, subset=feature_subset, eps_pctiles=percentiles)
    # print(pca_res)
    pca_results.append(pca_res)


# write results of cross-validation to a file
with open(fname, 'a') as the_file:

    the_file.write(
    f"""
    num_validation_sets:{num_validation_sets}
    val_ratio:{val_ratio}
    feature_subset:{feature_subset}
    dim_size:{dim_size}
    stagnation_time:{stagnation_time}
    percentiles:{percentiles}
    pairs_unsimilar_factor:{pairs_unsimilar_factor}
    pairs_trivial_factor:{pairs_trivial_factor}
    pairs_intra_trivial_factor:{pairs_intra_trivial_factor}
    pairs_max_similar:{pairs_max_similar}"""
    )

    the_file.write('\nEMBEDDING RESULTS:\n')
    for run_key in all_results[0].keys():
        the_file.write('\n --- {} ---'.format(run_key))
        for key in res[run_key].keys():
            category = [x[run_key][key] for x in all_results]
            mean = np.round(np.mean(category), 3)
            stdv = np.round(np.std(category) / np.sqrt(len(all_results)), 3)
            the_file.write('{}: {} , {}\n'.format(key, mean, stdv))

    the_file.write('\nPCA RESULTS:\n')
    for run_key in all_results[0].keys():
        the_file.write('\n --- {} ---'.format(run_key))
        for key in res[run_key].keys():
            category = [x[run_key][key] for x in pca_results]
            mean = np.round(np.mean(category), 3)
            stdv = np.round(np.std(category) / np.sqrt(len(pca_results)), 3)
            the_file.write('{}: {} , {}\n'.format(key, mean, stdv))

print('done')

# plt.clf()
# #plt.plot(labels_true)
# plt.plot(emb_labellings[0])
# plt.show()
