# Allow setting cores and RAM via env-vars, or use defaults
VB_CPUS = ENV['VB_CPUS'] || 2
VB_RAM = ENV['VB_RAM'] || 1024


Vagrant.configure(2) do |config|
	config.vm.box = "bento/ubuntu-22.04"

	config.vm.usable_port_range = 8000..8999
	config.vm.network "forwarded_port", guest: 80, host: 8080, auto_correct: true

	# Set a name in the log
	config.vm.define "ansible-workshop01" do ||
	end
	# Also set hostname
	config.vm.hostname = "ansible-workshop01"

	config.vm.provider "virtualbox" do |vb|
		#vb.gui = true
		vb.cpus = VB_CPUS
		vb.memory = VB_RAM
	end

	config.vm.provision "ansible" do |ansible|
		ansible.compatibility_mode = "2.0"
		ansible.config_file = "ansible/ansible.cfg"
		ansible.playbook = "ansible/site.yml"
	end
end
