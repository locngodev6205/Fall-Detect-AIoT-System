export function canCamera(camera, action) {
  return Boolean(camera?.permissions?.[action]);
}
