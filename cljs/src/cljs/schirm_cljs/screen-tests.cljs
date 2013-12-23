(ns schirm-cljs.screen-tests
  (:require [clojure.string :as string]
            [schirm-cljs.screen :as screen]
            [schirm-cljs.dom-utils :as dom-utils]))

(defn readable-styled-string [styled-string]
  (apply vector
         (:string styled-string)
         (sort (map keyword (remove empty? (-> styled-string :style screen/get-class-string (string/split \ )))))))

(defn into-styled-string [s & properties]
  (screen/StyledString. s (screen/get-style-from-classnames (map name properties))))

(defn line->readable [line]
  (->> line
       (map readable-styled-string)
       (into [])))

(defn readable->line
  [readable-line]
  (vec (map #(apply into-styled-string %) readable-line)))

(defn append-readable-line [parent line]
  (let [line-element (screen/create-line (readable->line line))]
    (.appendChild parent line-element)
    ;; lines are DIVs - no newline character required
    ;;(.appendChild parent (.createTextNode js/document "\n"))
    line-element))

(defn test-dom-line-op [line, expected, f]
  (when-not (dom-utils/select 'pre) (throw 'pre-node-is-missing))
  (let [line-element (append-readable-line (dom-utils/select 'pre) line)]
    (f line-element) ;; modifies the DOM
    (let [a (screen/read-line line-element)
          b (readable->line expected)]
      (if (= a b)
        :pass
        [:fail
         (list 'not= (-> line-element screen/read-line line->readable) expected)]))))

(defn run-tests []
  [
   ;; insert

   (test-dom-line-op []
                     [["ABC"]]
                     #(screen/line-insert % (into-styled-string "ABC") 0))
   (test-dom-line-op []
                     [["   ABC"]]
                     #(screen/line-insert % (into-styled-string "ABC") 3))   
   (test-dom-line-op [["A" :f-red]]
                     [["AB" :f-red]]
                     #(screen/line-insert % (into-styled-string "B" :f-red) 1))
   (test-dom-line-op [["A" :f-red]]
                     [["BA" :f-red]]
                     #(screen/line-insert % (into-styled-string "B" :f-red) 0))
   (test-dom-line-op [["A" :f-red]]
                     [["A" :f-red]
                      ["    "]
                      ["B" :f-red]]
                     #(screen/line-insert % (into-styled-string "B" :f-red) 5))
   (test-dom-line-op [["ABC" :f-red]]
                     [["ABxC" :f-red]]
                     #(screen/line-insert % (into-styled-string "x" :f-red) 2))
   (test-dom-line-op [["ABC" :f-red]]
                     [["AB" :f-red] ["xx" :f-blue :bold] ["C" :f-red]]
                     #(screen/line-insert % (into-styled-string "xx" :f-blue :bold) 2))
   (test-dom-line-op [["ABC" :f-red] ["DEF" :f-blue]]
                     [["ABC" :f-red] ["xxDEF" :f-blue]]
                     #(screen/line-insert % (into-styled-string "xx" :f-blue) 3))
   
   (test-dom-line-op [["ABC" :f-red] ["DEF" :f-blue]]
                     [["ABCxx" :f-red] ["DEF" :f-blue]]
                     #(screen/line-insert % (into-styled-string "xx" :f-red) 3))
   (test-dom-line-op [["ABC" :f-red] ["DEF" :f-blue]]
                     [["ABC" :f-red] ["xxDEF" :f-blue]]
                     #(screen/line-insert % (into-styled-string "xx" :f-blue) 3))
   
   ;; remove
   
   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-green] ["GHI" :f-red]]
                     [["AB" :f-blue] ["HI" :f-red]]
                     #(screen/line-remove % 2 5))
   
   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-red]]
                     [["AB" :f-blue] ["F" :f-red]]
                     #(screen/line-remove % 2 3))
   
   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-red]]
                     [["A" :f-blue]]
                     #(screen/line-remove % 1 5))
   
   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-red]]
                     [["F" :f-red]]
                     #(screen/line-remove % 0 5))
   
   (test-dom-line-op [["A" :f-blue] ["B" :f-red] ["C" :f-blue]]
                     [["AC" :f-blue]]
                     #(screen/line-remove % 1 1))
   
   (test-dom-line-op [["ABC" :f-blue] ["D" :f-red] ["E" :f-bold] ["FG" :f-blue]]
                     [["ABCG" :f-blue]]
                     #(screen/line-remove % 3 3))
   
   (test-dom-line-op [["AB" :f-blue] ["C" :f-blue :cursor] ["DEF" :f-blue]]
                     [["ABDEF" :f-blue]]
                     #(screen/line-remove % 2 1))
   
   (test-dom-line-op [["ABDEF" :f-blue]]
                     [["ABCDEF" :f-blue]]
                     #(screen/line-insert % (into-styled-string "C" :f-blue) 2))

   ;; insert-overwrite
   
   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-red]]
                     [["Axxx" :f-blue] ["EF" :f-red]]
                     #(screen/line-insert-overwrite % (into-styled-string "xxx" :f-blue) 1))

   (test-dom-line-op [["ABC" :f-blue] ["DEF" :f-red]]
                     [["A" :f-blue] ["xxxEF" :f-red]]
                     #(screen/line-insert-overwrite % (into-styled-string "xxx" :f-red) 1))

   (test-dom-line-op [["foo:" :f-green :b-default] ["$ " :f-default :b-default]]
                     [["foo:" :f-green :b-default] ["$ wxyz" :f-default :b-default]]
                     #(do
                        (screen/line-insert-overwrite % (into-styled-string "w" :f-default :b-default) 6)
                        (screen/line-insert-overwrite % (into-styled-string "x" :f-default :b-default) 7)
                        (screen/line-insert-overwrite % (into-styled-string "y" :f-default :b-default) 8)
                        (screen/line-insert-overwrite % (into-styled-string "z" :f-default :b-default) 9)))

   ;; cursor
   
   (test-dom-line-op [["ABCDEF" :f-blue]]
                     [["AB" :f-blue] ["C" :f-blue :cursor] ["DEF" :f-blue]]
                     #(screen/line-set-cursor % 2))

   (test-dom-line-op [["112233 " :f-blue]]
                     [["1122" :f-blue] ["3" :f-blue :cursor] ["3 " :f-blue]]
                     #(do
                        ;;(.log js/console "foo")
                        (screen/line-set-cursor % 6)
                        (screen/line-remove-cursor %)
                        (screen/line-set-cursor % 5)
                        (screen/line-remove-cursor %)
                        (screen/line-set-cursor % 4)))

   (test-dom-line-op [["AB" :f-blue] ["C" :f-blue :cursor] ["DEF" :f-blue]]
                     [["ABCDEF" :f-blue]]
                     #(screen/line-remove-cursor %))
   ])
