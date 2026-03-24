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
                output = subprocess.check_output(cmd).decode()
                if "Apple M" in output or "Radeon" in output:
                    specs["gpu_available"] = True
                    specs["gpu_details"] = "Apple Silicon / Discrete Mac GPU"
            elif specs["os"] == "Windows":
                import wmi
                w = wmi.WMI()
                for gpu in w.Win32_VideoController():
                    specs["gpu_available"] = True
                    specs["gpu_details"] = gpu.Name
            else: # Linux
                output = subprocess.check_output(["lspci"]).decode()
                if "NVIDIA" in output.upper() or "AMD" in output.upper():
                    specs["gpu_available"] = True
                    specs["gpu_details"] = "Discrete Linux GPU Detected"
        except Exception:
            pass

        return specs

    @staticmethod
    def calculate_concurrency():
        """Heuristic for max concurrency: 4 workers per core, capped by RAM (250MB/worker)."""
        specs = HardwareOptimizer.get_specs()
        
        # Concurrency by CPU (Network tasks can handle many threads)
        cpu_concurrency = specs["cpu_cores"] * 6 
        
        # Concurrency by RAM (Safety first)
        # Assuming each browser instance uses ~250MB
        ram_concurrency = int(specs["available_ram_gb"] * 1024 / 250)
        
        # Final decision: Minimum of CPU threads vs RAM capacity
        concurrency = max(5, min(cpu_concurrency, ram_concurrency))
        
        # If GPU is available, we can slightly bump it up as rendering load is offloaded
        if specs["gpu_available"]:
            concurrency = int(concurrency * 1.25)

        return concurrency, specs

if __name__ == "__main__":
    opt = HardwareOptimizer()
    conc, details = opt.calculate_concurrency()
    print(f"Optimal Concurrency: {conc}")
    print(f"Details: {details}")
