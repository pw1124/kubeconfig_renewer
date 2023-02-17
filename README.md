# Kubeconfig Renewer

A script that renews and updates a Kubernetes config file being held as a Secret variable on a repo on Github.  

This script is for the scenario where:

  * You are using Github Runners to deploy/interact with a Kubernetes cluster, and are using a kubeconfig file stored as a secret in your repo
  * The kubeconfig file, containing your cluster's CA certificate, client certificate, and client key, expired eventually, and you're getting an Error: Unauthorized when the Github workflow runs the step(s) requiring cluster authorization
  * Manually updating this kubeconfig file on Github Secrets is rather tedious 

Tested on Python 3.8.10.  PyOpenSSL >23.0.0 is also required.

### Usage

This script does the following:

  1. Loads the profile file from the `-p` or `--profile` argument
  2. Makes a subfolder in the current folder named `[timestamp][profile_name]`
  3. Generates a new private key and writes it to the subfolder
  4. Generates a CSR with specified Common Name and Organization.  Depending on your cluster's configuration, you should have these corresponding to the user or the group that has the privileges to interact with your cluster. Writes the CSR request to the subfolder.
  5. Loads the specified Kubernetes CA certificate (i.e. the one usually at `/etc/kubernetes/pki/ca.crt` if you created the cluster with kubeadm)
  6. Loads the specified Kubernetes CA key (i.e. the one usually at `/etc/kubernetes/pki/ca.key` if you created the cluster with kubeadm) --> Remember to use sudo to run the script if you're directly referring to these files in the profile!
  7. Signs the CSR from step 3 with the Kubernetes CA key and certificate, writes the signed CSR to the subfolder
  8. Reads the kubeconfig template file `kubeconfig.tpl` (provided) and populates the fields, writes the populated kubeconfig file to the subfolder
  9. Gets the public key used for encryption from Github.  You need to provide a Github Token with repo access.
  10. Base64 encodes and then encrypts the populated kubeconfig file using the public key from step 9
  11. Makes a request to Github to change the secret to the output from step 10. 

In essence, it creates a new signed certificate and updates the Github Secret.

### Sample Commands
```
python3 script.py -p profile.sample
```

There's also a `--dry-run` option where everything except step 11 is run.

```
python3 script.py -p profile.sample --dry-run
```

`profile.sample` is a required yaml file with the following fields:

```yaml
# name of profile (will be used as subfolder name and prefixes of generated files)
profile_name: my_profile 
# github token with repo access
github_token: github_token_with_repo_rights
# repo owner's username
github_user: your_username
# the repo itself
github_repo: repo_where_secret_is_located
# the name of the secret that contains the kubeconfig you wish to update
github_secret_name: name_of_secret
# the group with privileges to interact with your cluster
cert_organization_name: k8s_group
# the user with privileges to interact with your cluster
cert_common_name: k8s_name
# location of your cluster's ca.crt
k8s_ca_cert_path: /etc/kubernetes/pki/ca.crt
# location of your cluster's ca.key
k8s_ca_key_path: /etc/kubernetes/pki/ca.key
# location of kubeconfig.tpl, leave unchanged by default
kubeconfig_tpl_path: ./kubeconfig.tpl
# number of days you wish the new certificate to be valid for
renewal_days: 364
# name of your cluster
cluster_name: k8s_cluster
# endpoint of your cluster
cluster_endpoint: https://192.168.1.1:6443
# kubernetes namespace where the workflow will run
cluster_namespace: namespace
```
