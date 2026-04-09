{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    (python3.withPackages (ps: with ps; [
      pillow
      imagehash
      google-api-python-client
      google-auth-oauthlib
      google-auth-httplib2
    ]))
    sqlite
  ];
}
