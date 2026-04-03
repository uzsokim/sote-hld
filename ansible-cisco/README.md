# Ansible + VS Code + Cisco (Windows host, WSL recommended)

Ez a mappa egy minimal Ansible projektvaz Cisco eszkozokhoz.

## 1) Javasolt futtatasi mod (WSL2)

Windows alatt az Ansible control node-ot legstabilabban WSL2-ben (Ubuntu) erdemes futtatni, majd VS Code-bol a WSL-es ablakban megnyitni ezt a projektet.

### WSL engedelyezes (admin PowerShell)

Ezt egy **Administrator** PowerShell-ben futtasd:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Majd indits ujra a gepet, es telepits egy disztribuciot (pl. Ubuntu):

```powershell
wsl --install -d Ubuntu
```

Ha mar van Ubuntu, akkor eleg:

```powershell
wsl -d Ubuntu
```

### Ansible telepitese Ubuntu alatt

Ubuntu terminalban:

```bash
sudo apt update
sudo apt install -y python3 python3-pip openssh-client
python3 -m pip install --user ansible ansible-lint
python3 -m pip install --user paramiko netaddr
```

Cisco collectionok:

```bash
ansible-galaxy collection install cisco.ios ansible.netcommon
```

## 2) VS Code beallitas

- Telepitsd a VS Code extensionoket:
  - `Remote - WSL` (Microsoft)
  - `Ansible` (Red Hat)
  - `Python` (Microsoft)
- Nyiss egy `Remote - WSL` ablakot, es ott nyisd meg ezt a projektet.

## 3) Gyors ellenorzes (Cisco IOS pelda)

1. Tedd rendbe az inventory-t: `inventory/hosts.yml`
2. Add meg a belepesi adatokat kornyezeti valtozokkal (Ubuntu-ban):

```bash
export ANSIBLE_USER='admin'
export ANSIBLE_PASSWORD='...'
```

3. Futtatas:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/show_version.yml
```

## Biztonsagi megjegyzes

Prod kornyezetben javasolt `ansible-vault`-ot hasznalni jelszavakhoz, es a host key checkinget bekapcsolva hagyni.

