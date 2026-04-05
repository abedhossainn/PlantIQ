#!/usr/bin/env python3
"""
Generate RS256 key pair for JWT signing.

Usage:
    python generate_keys.py [--output-dir /path/to/secrets]
"""
import argparse
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


def generate_rsa_keypair(output_dir: Path, key_size: int = 2048):
    """
    Generate RS256 RSA key pair for JWT signing.
    
    Args:
        output_dir: Directory to save keys
        key_size: RSA key size in bits (minimum 2048)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating {key_size}-bit RSA key pair...")
    
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend()
    )
    
    # Save private key
    private_key_path = output_dir / "jwt-private.pem"
    with open(private_key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
        )
    print(f"✅ Private key saved to: {private_key_path}")
    
    # Generate public key
    public_key = private_key.public_key()
    
    # Save public key
    public_key_path = output_dir / "jwt-public.pem"
    with open(public_key_path, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
    print(f"✅ Public key saved to: {public_key_path}")
    
    # Set secure permissions (Unix only)
    try:
        private_key_path.chmod(0o600)  # rw-------
        public_key_path.chmod(0o644)   # rw-r--r--
        print("✅ Set secure file permissions")
    except Exception as e:
        print(f"⚠️  Could not set file permissions: {e}")
    
    print("\n📝 Next steps:")
    print(f"1. Copy {private_key_path} to FastAPI container (never expose externally)")
    print(f"2. Copy {public_key_path} to PostgREST container")
    print("3. Set environment variables:")
    print(f"   JWT_PRIVATE_KEY_PATH={private_key_path}")
    print(f"   JWT_PUBLIC_KEY_PATH={public_key_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate RS256 key pair for JWT signing"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./secrets"),
        help="Output directory for keys (default: ./secrets)"
    )
    parser.add_argument(
        "--key-size",
        type=int,
        default=2048,
        choices=[2048, 4096],
        help="RSA key size in bits (default: 2048)"
    )
    
    args = parser.parse_args()
    
    generate_rsa_keypair(args.output_dir, args.key_size)


if __name__ == "__main__":
    main()
