""" CellProfiler.Objects.py - represents a labelling of objects in an image

CellProfiler is distributed under the GNU General Public License.
See the accompanying file LICENSE for details.

Copyright (c) 2003-2009 Massachusetts Institute of Technology
Copyright (c) 2009-2010 Broad Institute
All rights reserved.

Please see the AUTHORS file for credits.

Website: http://www.cellprofiler.org
"""
__version__="$Revision$"

import decorator
import numpy as np
import scipy.sparse

@decorator.decorator
def memoize_method(function, *args):
    """Cache the result of a method in that class's dictionary
    
    The dictionary is indexed by function name and the values of that
    dictionary are themselves dictionaries with args[1:] as the keys
    and the result of applying function to args[1:] as the values.
    """
    sself = args[0]
    d = getattr(sself, "memoize_method_dictionary", False)
    if not d:
        d = {}
        setattr(sself,"memoize_method_dictionary",d)
    if not d.has_key(function):
        d[function] = {}
    if not d[function].has_key(args[1:]):
        d[function][args[1:]] = function(*args)
    return d[function][args[1:]]

        
class Objects(object):
    """Represents a segmentation of an image.

    IdentityPrimAutomatic produces three variants of its segmentation
    result. This object contains all three.
    """
    def __init__(self):
        self.__segmented = None
        self.__unedited_segmented = None
        self.__small_removed_segmented = None
        self.__parent_image = None
    
    def get_segmented(self):
        """Get the de-facto segmentation of the image into objects: a matrix 
        of object numbers.
        """
        return self.__segmented
    
    def set_segmented(self,labels):
        check_consistency(labels, self.__unedited_segmented, 
                          self.__small_removed_segmented)
        self.__segmented = downsample_labels(labels)
        # Clear all cached results.
        if getattr(self, "memoize_method_dictionary", False):
            self.memoize_method_dictionary = {}
    
    segmented = property(get_segmented,set_segmented)
    
    def has_unedited_segmented(self):
        """Return true if there is an unedited segmented matrix."""
        return self.__unedited_segmented != None
    
    def get_unedited_segmented(self):
        """Get the segmentation of the image into objects, including junk that 
        should be ignored: a matrix of object numbers.
        
        The default, if no unedited matrix is available, is the
        segmented labeling.
        """
        if self.__segmented != None:
            if self.__unedited_segmented != None:
                return self.__unedited_segmented
            return self.__segmented
        return self.__unedited_segmented
    
    def set_unedited_segmented(self,labels):
        check_consistency(self.__segmented, labels, 
                          self.__small_removed_segmented)
        self.__unedited_segmented = downsample_labels(labels)
    
    unedited_segmented = property(get_unedited_segmented, 
                                  set_unedited_segmented)
    
    def has_small_removed_segmented(self):
        """Return true if there is a junk object matrix."""
        return self.__small_removed_segmented != None
    
    def get_small_removed_segmented(self):
        """Get the matrix of segmented objects with the small objects removed
        
        This should be the same as the unedited_segmented label matrix with
        the small objects removed, but objects touching the sides of the image
        or the image mask still present.
        """
        if self.__small_removed_segmented != None:
            return self.__small_removed_segmented
        if self.__segmented != None:
            if self.has_unedited_segmented():
                return self.__unedited_segmented
            # If there's only a segmented, then there is no junk.
            return self.__segmented
        return self.__small_removed_segmented
    
    def set_small_removed_segmented(self,labels):
        check_consistency(self.__segmented, self.__unedited_segmented, labels)
        self.__small_removed_segmented = downsample_labels(labels)
    
    small_removed_segmented = property(get_small_removed_segmented, 
                                       set_small_removed_segmented)
    
    
    def get_parent_image(self):
        """The image that was analyzed to yield the objects.
        
        The image is an instance of CPImage which means it has the mask
        and crop mask.
        """
        return self.__parent_image
    
    def set_parent_image(self, parent_image):
        self.__parent_image = parent_image
        
    parent_image = property(get_parent_image, set_parent_image)
    
    def get_has_parent_image(self):
        """True if the objects were derived from a parent image
        
        """
        return self.__parent_image != None
    has_parent_image = property(get_has_parent_image)
    
    def crop_image_similarly(self, image):
        """Crop an image in the same way as the parent image was cropped."""
        if image.shape == self.segmented.shape:
            return image
        if self.parent_image == None:
            raise ValueError("Images are of different size and no parent image")
        return self.parent_image.crop_image_similarly(image)
    
    def relate_children(self, children):
        """Relate the object numbers in one label to the object numbers in another
        
        children - another "objects" instance: the labels of children within
                   the parent which is "self"
        
        Returns two 1-d arrays. The first gives the number of children within
        each parent. The second gives the mapping of each child to its parent's
        object number.
        """
        parent_labels = self.segmented
        child_labels = children.segmented
        # Apply cropping to the parent if done to the child
        try:
            parent_labels  = children.crop_image_similarly(parent_labels)
        except ValueError:
            # If parents and children are not similarly cropped, take the LCD
            parent_labels, child_labels = crop_labels_and_image(parent_labels,
                                                                child_labels)
        return self.relate_labels(parent_labels, child_labels)
    
    @staticmethod
    def relate_labels(parent_labels, child_labels):
        """Relate the object numbers in one label to the object numbers in another
        
        parent_labels - the parents which contain the children
        child_labels - the children to be mapped to a parent
        
        Returns two 1-d arrays. The first gives the number of children within
        each parent. The second gives the mapping of each child to its parent's
        object number.
        """
        parent_count = np.max(parent_labels)
        child_count = np.max(child_labels)
        any_parents = (parent_count > 0)
        any_children = (child_count > 0)
        if (not any_parents) and (not any_children):
            return np.zeros((0,), int),np.zeros((0,), int)
        elif (not any_parents):
            return np.zeros((0,), int),np.zeros((child_count,), int)
        elif (not any_children):
            return np.zeros((parent_count,), int), np.zeros((0,), int)
        #
        # Only look at points that are labeled in parent and child
        #
        not_zero = np.logical_and(parent_labels > 0,
                                     child_labels > 0)
        not_zero_count = np.sum(not_zero)
         
        histogram = scipy.sparse.coo_matrix((np.ones((not_zero_count,)),
                                             (parent_labels[not_zero],
                                              child_labels[not_zero])),
                                             shape=(parent_count+1,child_count+1))
        #
        # each row (axis = 0) is a parent
        # each column (axis = 1) is a child
        #
        histogram = histogram.toarray()
        parents_of_children = np.argmax(histogram,axis=0)
        #
        # Create a histogram of # of children per parent
        poc_histogram = scipy.sparse.coo_matrix((np.ones((child_count+1,)),
                                                 (parents_of_children,
                                                  np.zeros((child_count+1,),int))),
                                                 shape=(parent_count+1,1))
        children_per_parent = poc_histogram.toarray().flatten()
        #
        # Make sure to remove the background elements at index 0. Also,
        # there's something screwy about the arrays returned here - you
        # get "data type not supported" errors unless you reconstruct
        # the results.
        #
        children_per_parent = np.array(children_per_parent[1:].tolist(), int)
        parents_of_children = np.array(parents_of_children[1:].tolist(), int)
        return children_per_parent, parents_of_children
    
    @memoize_method
    def get_indices(self):
        """Get the indices for a scipy.ndimage-style function from the segmented labels
        
        """
        return np.array(range(np.max(self.segmented)), np.int32)+1
    
    indices = property(get_indices)
     
    @memoize_method
    def fn_of_label_and_index(self, function):
        """Call a function taking a label matrix with the segmented labels
        
        function - should have signature like
                   labels - label matrix
                   index  - sequence of label indices documenting which
                            label indices are of interest
        """
        return function(self.segmented,self.indices)
    
    @memoize_method
    def fn_of_ones_label_and_index(self,function):
        """Call a function taking an image, a label matrix and an index with an image of all ones
        
        function - should have signature like
                   image  - image with same dimensions as labels
                   labels - label matrix
                   index  - sequence of label indices documenting which
                            label indices are of interest
        Pass this function an "image" of all ones, for instance to compute
        a center or an area
        """
    
        return function(np.ones(self.segmented.shape),
                        self.segmented,
                        self.indices)
    
    @memoize_method
    def fn_of_image_label_and_index(self, function, image):
        """Call a function taking an image, a label matrix and an index
        
        function - should have signature like
                   image  - image with same dimensions as labels
                   labels - label matrix
                   index  - sequence of label indices documenting which
                            label indices are of interest
        """
        return function(image,
                self.segmented,
                self.indices)

def check_consistency(segmented, unedited_segmented, small_removed_segmented):
    """Check the three components of Objects to make sure they are consistent
    """
    assert segmented == None or segmented.ndim == 2, "Segmented label matrix must have two dimensions, has %d"%(segmented.ndim)
    assert unedited_segmented == None or unedited_segmented.ndim == 2, "Unedited segmented label matrix must have two dimensions, has %d"%(unedited_segmented.ndim)
    assert small_removed_segmented == None or small_removed_segmented.ndim == 2, "Small removed segmented label matrix must have two dimensions, has %d"%(small_removed_segmented.ndim)
    assert segmented == None or unedited_segmented == None or segmented.shape == unedited_segmented.shape, "Segmented %s and unedited segmented %s shapes differ"%(repr(segmented.shape),repr(unedited_segmented.shape))
    assert segmented == None or small_removed_segmented == None or segmented.shape == small_removed_segmented.shape, "Segmented %s and small removed segmented %s shapes differ"%(repr(segmented.shape),repr(small_removed_segmented.shape))
   

class ObjectSet(object):
    """A set of objects.Objects instances.
    
    This class allows you to either refer to an object by name or
    iterate over all available objects.
    """
    
    def __init__(self, can_overwrite = False):
        """Initialize the object set
        
        can_overwrite - True to allow overwriting of a new copy of objects
                        over an old one of the same name (for debugging)
        """
        self.__objects_by_name = {}
        self.__can_overwrite = can_overwrite
    
    def add_objects(self, objects, name):
        assert isinstance(objects,Objects), "objects must be an instance of CellProfiler.Objects"
        assert ((not self.__objects_by_name.has_key(name)) or
                self.__can_overwrite), "The object, %s, is already in the object set"%(name)
        self.__objects_by_name[name] = objects
    
    def get_object_names(self):
        """Return the names of all of the objects
        """
        return self.__objects_by_name.keys()
    
    object_names = property(get_object_names)
    
    def get_objects(self,name):
        """Return the objects instance with the given name
        """
        return self.__objects_by_name[name]
    
    def get_all_objects(self):
        """Return a list of name / objects tuples
        """
        return self.__objects_by_name.items()
    
    all_objects = property(get_all_objects)

def downsample_labels(labels):
    '''Convert a labels matrix to the smallest possible integer format'''
    labels_max = np.max(labels)
    if labels_max < 128:
        return labels.astype(np.int8)
    elif labels_max < 32768:
        return labels.astype(np.int16)
    return labels.astype(np.int32)

def crop_labels_and_image(labels, image):
    '''Crop a labels matrix and an image to the lowest common size
    
    labels - a n x m labels matrix
    image - a 2-d or 3-d image
    
    Assumes that points outside of the common boundary should be masked.
    '''
    min_height = min(labels.shape[0], image.shape[0])
    min_width = min(labels.shape[1], image.shape[1])
    if image.ndim == 2:
        return (labels[:min_height, :min_width], 
                image[:min_height, :min_width])
    else:
        return (labels[:min_height, :min_width], 
                image[:min_height, :min_width,:])
    
def size_similarly(labels, secondary):
    '''Size the secondary matrix similarly to the labels matrix
    
    labels - labels matrix
    secondary - a secondary image or labels matrix which might be of
                different size.
    Return the resized secondary matrix and a mask indicating what portion
    of the secondary matrix is bogus (manufactured values).
    
    Either the mask is all ones or the result is a copy, so you can
    modify the output within the unmasked region w/o destroying the original.
    '''
    assert secondary.ndim == 2
    if labels.shape == secondary.shape:
        return secondary, np.ones(secondary.shape, bool)
    if (labels.shape[0] <= secondary.shape[0] and
        labels.shape[1] <= secondary.shape[1]):
        return (secondary[:labels.shape[0], :labels.shape[1]],
                np.ones(labels.shape, bool))
    #
    # Some portion of the secondary matrix does not cover the labels
    #
    result = np.zeros(labels.shape, secondary.dtype)
    i_max = min(secondary.shape[0], labels.shape[0])
    j_max = min(secondary.shape[1], labels.shape[1])
    result[:i_max,:j_max] = secondary[:i_max, :j_max]
    mask = np.zeros(labels.shape, bool)
    mask[:i_max, :j_max] = 1
    return result, mask

