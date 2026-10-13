import QtQuick

QtObject {
  property bool waitForEnd: false
  property string content: ""

  signal streamFinished(string text)
}
