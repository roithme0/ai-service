export function sameContract(left, right) {
  return (
    left.toString('utf8').replaceAll('\r\n', '\n') ===
    right.toString('utf8').replaceAll('\r\n', '\n')
  );
}
