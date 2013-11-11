(ns modern-cljs.connect
  (:require [clojure.browser.repl :as repl]))

(defn init []
  (set! (.-onreadystatechange js/document)
        #(when (== (.-readyState js/document) "complete")
           (repl/connect "http://localhost:9000/repl"))))

(init)
