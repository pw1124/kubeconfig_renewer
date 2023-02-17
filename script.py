import sys, getopt, requests, json, datetime, os, base64, yaml
from base64 import b64encode
from nacl import encoding, public
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from string import Template
from colorama import Fore, Back, Style

def main(argv):

   profile_path = ''
   dry_run = False
   try:
      opts, args = getopt.getopt(argv,"hp:",["profile=", "dry-run"])
   except getopt.GetoptError:
      print ('script.py -p <profile> --dry-run')
      sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
         print ('script.py -p <profile> --dry-run')
         sys.exit()
      elif opt in ("-p", "--profile"):
         profile_path = arg
      elif opt == "--dry-run":
         dry_run = True

   print (Fore.YELLOW + '\nDry run selected, generating cert folder but not uploading to Github...' if dry_run else '')

   print (Fore.GREEN + 'Reading profile from ' + Style.RESET_ALL + profile_path)
   with open(profile_path, 'r') as file:
      profile = yaml.load(file, Loader=yaml.FullLoader)

   # workaround because i can't get a redacter working with json.dumps
   github_token = profile["github_token"]
   profile["github_token"] = "<redacted>"

   print (Fore.GREEN + 'Profile file contents:' + Style.RESET_ALL)
   print(json.dumps(profile, indent=4))

   now = datetime.datetime.now()
   new_dir_path = now.strftime("%Y-%m-%d-%H-%M-%S") + profile["profile_name"]
   os.mkdir("./" + new_dir_path)
   print (Fore.GREEN + '\nMaking new subfolder at ' + Style.RESET_ALL + "./" + new_dir_path)

   relative_new_dir_path = "./" + new_dir_path + "/"

   private_key = rsa.generate_private_key(
     public_exponent=65537,
     key_size=2048
   )

   unencrypted_pem_private_key = private_key.private_bytes(
     encoding=serialization.Encoding.PEM,
     format=serialization.PrivateFormat.TraditionalOpenSSL,
     encryption_algorithm=serialization.NoEncryption()
   )

   print (Fore.GREEN + '\nGenerating private key...\n ' + Style.RESET_ALL + unencrypted_pem_private_key.decode("utf-8")[:100] + "...")

   b64_encoded_client_key = b64encode(unencrypted_pem_private_key).decode('ascii')

   private_key_path = relative_new_dir_path + profile["profile_name"] + ".key"
   print (Fore.GREEN + 'Writing new private key file to ' + Fore.CYAN + private_key_path + Style.RESET_ALL)
   with open(private_key_path, "wb") as csr_file:
     csr_file.write(unencrypted_pem_private_key)

   print (Fore.GREEN + '\nGenerating certificate signing request with CN = ' + Style.RESET_ALL +
          profile["cert_common_name"] +
          Fore.GREEN + " and O = " + Style.RESET_ALL +
          profile["cert_organization_name"])

   csr = x509.CertificateSigningRequestBuilder().subject_name(
     x509.Name([
         x509.NameAttribute(x509.NameOID.COMMON_NAME, profile["cert_common_name"]),
         x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, profile["cert_organization_name"]),
     ])
   ).sign(private_key, hashes.SHA256())

   print (Fore.GREEN + "Generated CSR contents: \n " + Style.RESET_ALL + csr.public_bytes(serialization.Encoding.PEM).decode('utf-8')[:100] + "...")

   csr_path = relative_new_dir_path + profile["profile_name"] + ".csr"
   print (Fore.GREEN + 'Writing CSR file to ' + Fore.CYAN + csr_path + Style.RESET_ALL)
   with open(csr_path, "wb") as csr_file:
     csr_file.write(csr.public_bytes(serialization.Encoding.PEM))

   print (Fore.GREEN + '\nReading Kubernetes CA certificate file from ' + Style.RESET_ALL + profile["k8s_ca_cert_path"])
   with open(profile["k8s_ca_cert_path"], "rb") as ca_cert_file:
     ca_cert_contents = ca_cert_file.read()

   ca_cert = x509.load_pem_x509_certificate(ca_cert_contents)

   b64_encoded_ca_cert = b64encode(ca_cert_contents).decode('ascii')

   print (Fore.GREEN + 'Reading Kubernetes key file from ' + Style.RESET_ALL + profile["k8s_ca_key_path"])
   with open(profile["k8s_ca_key_path"], "rb") as ca_key_file:
     ca_private_key = serialization.load_pem_private_key(
       ca_key_file.read(),
       password=None
     )

   print (Fore.GREEN + '\nSigning the generated certificate signing request with key file above... ' + Style.RESET_ALL, end='')
   builder = x509.CertificateBuilder().subject_name(csr.subject) \
                                   .issuer_name(ca_cert.subject) \
                                   .public_key(csr.public_key()) \
                                   .serial_number(x509.random_serial_number()) \
                                   .not_valid_before(datetime.datetime.utcnow()) \
                                   .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=profile["renewal_days"]))
   cert = builder.sign(private_key=ca_private_key, algorithm=hashes.SHA256())
   print ("DONE")

   certbytes = cert.public_bytes(serialization.Encoding.PEM)

   print (Fore.GREEN + 'Signed certificate contents: \n' + Style.RESET_ALL
          + certbytes.decode('utf-8')[:100] + "...")

   b64_encoded_cert = b64encode(certbytes).decode('ascii')

   signed_cert_path = relative_new_dir_path + profile["profile_name"] + ".crt"
   print (Fore.GREEN + 'Writing the new signed certificate to ' + Fore.CYAN + signed_cert_path + Style.RESET_ALL)
   with open(signed_cert_path, "wb") as cert_file:
     cert_file.write(certbytes)

   print (Fore.GREEN + '\nReading the kubeconfig template file from ' + Style.RESET_ALL + profile["kubeconfig_tpl_path"])
   with open(profile["kubeconfig_tpl_path"], "r") as kubeconfigtemplate_file:
     kubeconfigtemplate = Template(kubeconfigtemplate_file.read())

   print (Fore.GREEN + 'Populating template... ' + Style.RESET_ALL, end="")
   kubeconfig_subbed = kubeconfigtemplate.substitute(
        CLUSTER_NAME=profile["cluster_name"],
        CLUSTER_CA=b64_encoded_ca_cert,
        CLUSTER_ENDPOINT=profile["cluster_endpoint"],
        USER=profile["cert_common_name"],
        CLIENT_CERTIFICATE_DATA=b64_encoded_cert,
        NAMESPACE=profile["cluster_namespace"],
        CLIENT_KEY_DATA=b64_encoded_client_key
     )
   print("DONE")

   new_kubeconfig_path = relative_new_dir_path + profile["profile_name"] + "_kubeconfig"
   print (Fore.GREEN + 'Writing populated kubeconfig template file to ' + Fore.CYAN + new_kubeconfig_path + Style.RESET_ALL)
   with open(new_kubeconfig_path, "w") as kubeconfig_final_file:
     kubeconfig_final_file.write(kubeconfig_subbed)

   github_api_headers = {
     'Accept':'application/vnd.github+json',
     'Authorization': 'Bearer ' + github_token,
     'X-GitHub-Api-Version':'2022-11-28'
   }

   github_api_url = "https://api.github.com/repos/" + profile["github_user"] + "/" + profile["github_repo"]

   public_key_url = github_api_url + "/actions/secrets/public-key"
   print (Fore.GREEN + '\nGetting public key for encryption from ' + Style.RESET_ALL + public_key_url)
   public_key_json = requests.get(public_key_url, headers=github_api_headers)
   public_key_obj = json.loads(public_key_json.content)

   print (Fore.GREEN + "Response: \n" + Style.RESET_ALL + json.dumps(public_key_obj, indent=4))

   public_key = public_key_obj['key']
   public_key_id = public_key_obj['key_id']

   print (Fore.GREEN + "\nBase64 encoding the populated kubeconfig and then encrypting it with the received key..." + Style.RESET_ALL, end="")
   public_key_enc = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
   sealed_box = public.SealedBox(public_key_enc)
   b64_encoded_msg = b64encode(kubeconfig_subbed.encode("utf-8"))
   encrypted = sealed_box.encrypt(b64_encoded_msg)
   encrypted_msg = b64encode(encrypted).decode("utf-8")
   print ("DONE")
   print(Fore.GREEN + "Encrypted message: " + Style.RESET_ALL + encrypted_msg[:50] + "...")

   update_body = {
     'encrypted_value': encrypted_msg,
     'key_id': public_key_id
   }

   if not dry_run:
     print(Fore.GREEN + "Uploading to Github and changing the " + Fore.RED + profile["github_secret_name"] + Fore.GREEN + " secret to the new kubeconfig")
     update_secret_response = requests.put(github_api_url + "/actions/secrets/" + profile["github_secret_name"], headers=github_api_headers, data=json.dumps(update_body))
     if update_secret_response.status_code == 204:
        print(Fore.GREEN + "Secret successfully updated!" + Style.RESET_ALL)
     else:
        print(Fore.RED + "Unknown response code, please try again" + Style.RESET_ALL)
   else:
     print(Fore.YELLOW + "\nDry Run selected, not uploading to Github\n" + Fore.MAGENTA + "\n*** All Done! ***\n" + Style.RESET_ALL)

if __name__ == "__main__":
   main(sys.argv[1:])
