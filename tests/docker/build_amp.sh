set -e
cd /home/user/appmanager-pro
rm -rf ${S}/ampbuild/ctx/app ${S}/ampbuild/ctx/assets && cp -r app assets ${S}/ampbuild/ctx/ && find ${S}/ampbuild/ctx -name __pycache__ -prune -exec rm -rf {} +
cd ${S}/ampbuild/ctx
docker build -q --build-arg BUILD_TAG=1 -t localhost:5000/amp:1 . >/dev/null
docker build -q --build-arg BUILD_TAG=2 -t localhost:5000/amp:2 . >/dev/null
docker build -q -t localhost:5000/amp:bad -f ${S}/ampbuild/Dockerfile.bad ${S}/ampbuild >/dev/null
for t in 1 2 bad; do docker push -q localhost:5000/amp:$t >/dev/null; done
echo built
