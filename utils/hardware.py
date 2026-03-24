import os
import platform
import psutil
import subprocess

class HardwareOptimizer:
    @staticmethod
    def get_specs():
        """Detect OS, CPU, RAM, and GPU presence."""
        specs = {
            "os": platform.system(),
            "cpu_cores": os.cpu_count() or 4,
            "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "available_ram_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "gpu_available": False,
            "gpu_details": "None"
        }

        # GPU Detection
        try:
            if specs["os"] == "Darwin":
                # Check for Apple Silicon or discrete GPU on Mac
                cmd = ["system_profiler", "SPDisplaysDataType"]
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
                if "Apple M" in output or "Radeon" in output:
                    specs["gpu_available"] = True
                    specs["gpu_details"] = "Apple Silicon / Discrete Mac GPU"
            elif specs["os"] == "Windows":
                # Use standard wmic command to avoid third-party 'wmi' dependency
                cmd = ["wmic", "path", "win32_VideoController", "get", "name"]
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
                clean_output = [line.strip() for line in output.split("\n") if line.strip() and "Name" not in line]
                if clean_output:
                    specs["gpu_available"] = True
                    specs["gpu_details"] = ", ".join(clean_output)
            else: # Linux
                # Check for NVIDIA specifically via nvidia-smi
                try:
                    nv_output = subprocess.check_output(["nvidia-smi", "-L"], stderr=subprocess.DEVNULL).decode()
                    if "GPU" in nv_output:
                        specs["gpu_available"] = True
                        specs["gpu_details"] = nv_output.strip().split("\n")[0]
                except Exception:
                    # Fallback to lspci for Intel/AMD
                    try:
                        lspci_output = subprocess.check_output(["lspci"], stderr=subprocess.DEVNULL).decode()
                        if "VGA" in lspci_output or "3D" in lspci_output:
                            specs["gpu_available"] = True
                            specs["gpu_details"] = "Linux Integrated/Discrete GPU Detected"
                    except Exception:
                        pass
        except Exception:
            pass

        return specs

    @staticmethod
    def calculate_concurrency():
        """Heuristic for max concurrency: 8 workers per core if RAM allows."""
        specs = HardwareOptimizer.get_specs()
        
        # Explicit casts to prevent type-guessing errors
        cores = int(specs["cpu_cores"])
        avail_ram = float(specs["available_ram_gb"])
        
        # Concurrency by CPU: 8 workers per core is safe for high-density IO tasks
        cpu_concurrency = cores * 8 
        
        # Concurrency by RAM: 250MB per worker safety margin
        # We use 80% of available RAM as a safe upper bound
        safe_ram_mb = (avail_ram * 1024.0) * 0.8
        ram_concurrency = int(safe_ram_mb / 250)
        
        # Final decision: Min of CPU threads vs RAM capacity, floor at 10
        concurrency = float(max(10, min(cpu_concurrency, ram_concurrency)))
        
        # If GPU is available, we bump processing by 20%
        if specs["gpu_available"]:
            concurrency = int(concurrency * 1.2)
        else:
            concurrency = int(concurrency)

        return concurrency, specs

if __name__ == "__main__":
    opt = HardwareOptimizer()
    conc, details = opt.calculate_concurrency()
    print(f"Optimal Concurrency: {conc}")
    print(f"Details: {details}")
